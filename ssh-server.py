"""
A small SSH + SFTP server in pure Python (paramiko), for places where no real sshd can run.

Written for Samsung's Secure Folder ("My Safe", Android user 150): Termux cannot be installed
there, and Knox shuts adb out of it entirely, so an app running INSIDE the folder is the only
way in - here Pydroid. Start this script from Pydroid inside the folder and keep it in front;
it serves:

- exec requests (ssh host "command"), with stdin/stdout/stderr and the exit status. This is
  what ssh_script_runner.py and myLibs.sshUtils rely on.
- an interactive shell (ssh host), with a pty when the client asks for one.
- the sftp subsystem, over the real filesystem, so sftp and paramiko's open_sftp work.

Every command runs through Android's /system/bin/sh with `python`/`python3` defined as shell
functions pointing at this very interpreter. Functions rather than a wrapper script on PATH,
because an app targeting a recent Android may not execute files from its own data folder,
while Pydroid's interpreter itself is obviously allowed to run. For the same reason `bash`
falls back to sh when no bash exists (ssh_script_runner.py runs every .sh through bash).

Authentication is by public key only, against AUTHORIZED_KEYS below plus an optional
authorized_keys file in SERVER_HOME. Any username is accepted - there is only one user here.

Reach it over USB with `adb forward tcp:8023 tcp:8023` on the PC, then 127.0.0.1:8023.

It lives in SSH_COPY for that folder's libraries, so the whole folder has to be next to it -
simple-remote-copy.py copies every .py of it - and Pydroid needs `termcolor` as well as `paramiko`.
"""
import sys; from pathlib import Path; p = Path(__file__).resolve().parent; __package__ = p.name; sys.path.append(p.parent.as_posix()) # To be able to use relative imports

import errno
import fcntl
import logging
import os
import pty
import shlex
import socket
import struct
import subprocess
import termios
import threading
from collections.abc import Callable

import paramiko
from termcolor import colored as clr

from .commonConstants import COLOR_ERROR, COLOR_WARN
from .fileUtils import ensureFolderExists, readLines, writeTextFile
from .SimpleError import SimpleError

#* configuration

LISTEN_ADDRESS = "0.0.0.0"
PORT           = 8023 # Termux's sshd already has 8022
SERVER_HOME    = os.path.expanduser("~")
HOST_KEY_FILE  = os.path.join(SERVER_HOME, ".ssh-server-host-key")
SHELL_RC_FILE  = os.path.join(SERVER_HOME, ".ssh-server-shrc")
LOG_FILE       = os.path.join(SERVER_HOME, "temp", "ssh-server.log") # Appended to across runs, so it can be read over ssh
SHELL          = "/system/bin/sh" if os.path.exists("/system/bin/sh") else "/bin/sh"
BUFFER_SIZE    = 64 * 1024

# Public keys, one OpenSSH line each - not secrets. Lines from SERVER_HOME/authorized_keys are added too.
AUTHORIZED_KEYS = [
	"ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQCa1YL4BEuh0b0kllA6wbwnXIItqANWYMkxaNmlE1SQbVrNY6fTx43h+G/d8gqrrBlJPBDe7dRmHA/TR5+fnCCdRe9OKgGWNcW1MxeAT8KTkqL0K7Jb1Bk2rOpvykDQvQaICFSxxDTyFEOfj9pOT+GcasmW4SOn8/iDsVgdVegOBbSbtxHzLnW14EVNxEZzeI0HnJsXy6f+1bRQxdlguJluCUih7DJIK1ANyDiP4oGLVRDp7+3Vk3d+DAlrpimczfNeW04NJTKelSdlXvT0gvxAZnYXY04onmcCEdnn51IsTfdeW+KWm3SL0aLs+izpq60WjoQ5yfrt0Am7VTgcCVUhpXaNogBw5t/snRbUWWl/yAwAICAAEwc53ewdMB9gcqzylL+3NjuiQFxroBDouImuvwNMG+dqvdXqxW/esd3c3Jcr0MmmVR+L6KKkKh88jgYxhSrVFRr7tfDmbmmgAVdrewKIYERDh1tHjXY6bUD6cmvbiFo3BRyJemm087IjV+Wsj8O+RMTxikut/CwRA5fmMORMLcUjzlPFWDfIL0ihrKlKjeBOnniPozqLl2Xxj2I76QFflC5q+exGCKJTJKO8HbFTcdjO6sOfbiMKEnPUX+fmhH+Ls1cpszPojnBqGg21JijDXvrACLuI3l89CKNMBVtxBwiKZor71yoRKeXN2Q== fryderyk@Fryderyk",
]

#* helpers

logger = logging.getLogger("ssh-server")

LEVEL_COLORS = {logging.WARNING: COLOR_WARN, logging.ERROR: COLOR_ERROR, logging.CRITICAL: COLOR_ERROR}

class ColoredFormatter(logging.Formatter):
	"""The console only: warnings and errors in the usual SSH_COPY colours. The log file stays plain."""
	def format(self, record: logging.LogRecord) -> str:
		text = super().format(record)
		color = LEVEL_COLORS.get(record.levelno)
		return clr(text, color) if color else text

def setup_logging() -> None:
	"""
	Everything goes to the Pydroid console (short time) and to LOG_FILE (full local timestamp
	and level). paramiko's own warnings and errors - a transport or SFTP exception with its
	traceback - land in both too, as does anything uncaught, in any thread.
	"""
	ensureFolderExists(os.path.dirname(LOG_FILE))
	console = logging.StreamHandler(sys.stdout)
	console.setFormatter(ColoredFormatter("%(asctime)s %(message)s", "%H:%M:%S"))
	file = logging.FileHandler(LOG_FILE, encoding="utf-8")
	file.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%dT%H:%M:%S%z"))
	root = logging.getLogger()
	root.setLevel(logging.INFO)
	root.addHandler(console)
	root.addHandler(file)
	logging.getLogger("paramiko").setLevel(logging.WARNING) # INFO would log every key exchange
	sys.excepthook = lambda kind, value, trace: logger.critical("uncaught exception", exc_info=(kind, value, trace))
	threading.excepthook = lambda hook: logger.error(f"uncaught exception in thread {hook.thread.name if hook.thread else '?'}", exc_info=(hook.exc_type, hook.exc_value, hook.exc_traceback))

def log(message: str) -> None:
	logger.info(message)

def describe(command: str | None) -> str:
	if command is None:
		return "interactive shell"
	return command if len(command) <= 120 else command[:117] + "..."

def load_authorized_keys() -> set[str]:
	"""The base64 blobs of every allowed key; the type and comment around them do not matter."""
	lines = list(AUTHORIZED_KEYS)
	extra_file = os.path.join(SERVER_HOME, "authorized_keys")
	if os.path.isfile(extra_file):
		lines += readLines(extra_file)
	return {line.split()[1] for line in lines if len(line.split()) >= 2 and not line.startswith("#")}

def load_or_create_host_key() -> paramiko.PKey:
	"""Keep one host key across restarts, so a client that remembers it does not start complaining."""
	if os.path.isfile(HOST_KEY_FILE):
		return paramiko.ECDSAKey.from_private_key_file(HOST_KEY_FILE)
	key = paramiko.ECDSAKey.generate(bits=256)
	key.write_private_key_file(HOST_KEY_FILE)
	log(f"created a new host key: {HOST_KEY_FILE}")
	return key

def shell_prelude() -> str:
	"""Shell functions that make `python` mean this interpreter, and `bash` fall back to sh."""
	interpreter = shlex.quote(sys.executable)
	return (
		f'python() {{ {interpreter} "$@"; }}\n'
		f'python3() {{ {interpreter} "$@"; }}\n'
		'command -v bash >/dev/null 2>&1 || bash() { sh "$@"; }\n'
	)

def build_environment(term: str | None) -> dict[str, str]:
	environment = dict(os.environ)
	environment["HOME"]  = SERVER_HOME
	environment["SHELL"] = SHELL
	environment["ENV"]   = SHELL_RC_FILE # An interactive mksh sources $ENV - that is how a shell gets the prelude
	path_parts = [part for part in environment.get("PATH", "").split(":") if part]
	for folder in ("/system/bin", "/system/xbin"):
		if folder not in path_parts:
			path_parts.append(folder)
	environment["PATH"] = ":".join(path_parts)
	if term:
		environment["TERM"] = term
	return environment

def set_window_size(fd: int, width: int, height: int) -> None:
	fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", height, width, 0, 0))

def exit_code_of(process: subprocess.Popen) -> int:
	"""Killed by signal N is reported as 128+N, the way a shell reports it."""
	return 128 - process.returncode if process.returncode < 0 else process.returncode

#region #* one session channel: an exec or a shell

class Session:
	def __init__(self, channel: paramiko.Channel) -> None:
		self.channel = channel
		self.term: str | None = None
		self.size = (80, 24)
		self.wants_pty = False
		self.master_fd: int | None = None

	def resize(self, width: int, height: int) -> None:
		self.size = (width, height)
		if self.master_fd is not None:
			set_window_size(self.master_fd, width, height)

	def start(self, command: str | None) -> None:
		threading.Thread(target=self.run, args=(command,), daemon=True).start()

	def run(self, command: str | None) -> None:
		"""Run the command (None = an interactive shell), then report its exit status and close."""
		argv = [SHELL, "-c", shell_prelude() + command] if command is not None else [SHELL, "-i"]
		environment = build_environment(self.term)
		try:
			exit_code = None
			if self.wants_pty:
				try:
					master_fd, slave_fd = pty.openpty()
				except OSError as error:
					# Pydroid in Secure Folder gets "out of pty devices" - SELinux keeps the app
					# off /dev/ptmx. Pipes still give a working, if line-mode, shell.
					log(f"  no pty ({error.strerror or error}), using pipes") # "out of pty devices" comes without an errno, so no strerror
				else:
					exit_code = self.run_with_pty(master_fd, slave_fd, argv, environment)
			if exit_code is None:
				exit_code = self.run_with_pipes(argv, environment)
		except Exception as error:
			logger.exception(f"  failed to run: {describe(command)}")
			self.safe_send(self.channel.sendall_stderr, f"ssh-server: {error!r}\n".encode())
			exit_code = 127
		log(f"  exit {exit_code}: {describe(command)}")
		try:
			self.channel.send_exit_status(exit_code)
		finally:
			self.channel.close()

	def run_with_pipes(self, argv: list[str], environment: dict[str, str]) -> int:
		process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=SERVER_HOME, env=environment)
		pumps = [
			threading.Thread(target=self.pump_out, args=(process.stdout.fileno(), self.channel.sendall, process), daemon=True),
			threading.Thread(target=self.pump_out, args=(process.stderr.fileno(), self.channel.sendall_stderr, process), daemon=True),
		]
		for pump in pumps:
			pump.start()
		threading.Thread(target=self.pump_in_pipe, args=(process,), daemon=True).start()
		process.wait()
		for pump in pumps:
			pump.join() # The pipes reach EOF once the process and anything it spawned have closed them
		return exit_code_of(process)

	def run_with_pty(self, master_fd: int, slave_fd: int, argv: list[str], environment: dict[str, str]) -> int:
		self.master_fd = master_fd
		set_window_size(master_fd, *self.size)
		process = subprocess.Popen(argv, stdin=slave_fd, stdout=slave_fd, stderr=slave_fd, cwd=SERVER_HOME, env=environment, start_new_session=True)
		os.close(slave_fd)
		output = threading.Thread(target=self.pump_out, args=(master_fd, self.channel.sendall, process), daemon=True)
		output.start()
		threading.Thread(target=self.pump_in_pty, args=(master_fd,), daemon=True).start()
		process.wait()
		output.join(timeout=2) # A background child may keep the pty open - do not wait on it forever
		self.master_fd = None
		os.close(master_fd)
		return exit_code_of(process)

	def pump_out(self, fd: int, send: Callable[[bytes], None], process: subprocess.Popen) -> None:
		while True:
			try:
				data = os.read(fd, BUFFER_SIZE)
			except OSError: # EIO on a pty whose last writer is gone - that is its EOF
				return
			if not data:
				return
			if not self.safe_send(send, data):
				process.kill() # The client is gone, nobody would read the rest
				return

	def pump_in_pipe(self, process: subprocess.Popen) -> None:
		try:
			while data := self.channel.recv(BUFFER_SIZE):
				process.stdin.write(data)
				process.stdin.flush()
		except (OSError, EOFError):
			pass
		finally:
			try:
				process.stdin.close()
			except OSError:
				pass

	def pump_in_pty(self, master_fd: int) -> None:
		try:
			while data := self.channel.recv(BUFFER_SIZE):
				os.write(master_fd, data)
		except (OSError, EOFError):
			pass

	@staticmethod
	def safe_send(send: Callable[[bytes], None], data: bytes) -> bool:
		try:
			send(data)
			return True
		except (OSError, EOFError, paramiko.SSHException):
			return False
#endregion

#region #* the SSH side

class Server(paramiko.ServerInterface):
	def __init__(self, authorized_keys: set[str]) -> None:
		self.authorized_keys = authorized_keys
		self.sessions: dict[int, Session] = {}

	def session_for(self, channel: paramiko.Channel) -> Session:
		return self.sessions.setdefault(channel.get_id(), Session(channel))

	def get_allowed_auths(self, username: str) -> str:
		return "publickey"

	def check_auth_publickey(self, username: str, key: paramiko.PKey) -> int:
		if key.get_base64() in self.authorized_keys:
			log(f"  authenticated as {username} ({key.get_name()})")
			return paramiko.AUTH_SUCCESSFUL
		return paramiko.AUTH_FAILED

	def check_channel_request(self, kind: str, chanid: int) -> int:
		if kind == "session":
			return paramiko.OPEN_SUCCEEDED
		return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

	def check_channel_pty_request(self, channel: paramiko.Channel, term: bytes | str, width: int, height: int, pixelwidth: int, pixelheight: int, modes: bytes) -> bool:
		session = self.session_for(channel)
		session.wants_pty = True
		session.term = term.decode(errors="replace") if isinstance(term, bytes) else term
		session.size = (width, height)
		return True

	def check_channel_window_change_request(self, channel: paramiko.Channel, width: int, height: int, pixelwidth: int, pixelheight: int) -> bool:
		self.session_for(channel).resize(width, height)
		return True

	def check_channel_exec_request(self, channel: paramiko.Channel, command: bytes) -> bool:
		text = command.decode("utf-8", errors="replace")
		log(f"  exec: {describe(text)}")
		self.session_for(channel).start(text)
		return True

	def check_channel_shell_request(self, channel: paramiko.Channel) -> bool:
		log("  shell")
		self.session_for(channel).start(None)
		return True
#endregion

#region #* the SFTP side: the real filesystem, relative paths resolved against SERVER_HOME

def sftp_error(error: OSError) -> int:
	return paramiko.SFTPServer.convert_errno(error.errno)

class LocalSftpHandle(paramiko.SFTPHandle):
	def stat(self) -> paramiko.SFTPAttributes | int:
		try:
			return paramiko.SFTPAttributes.from_stat(os.fstat(self.readfile.fileno()))
		except OSError as error:
			return sftp_error(error)

	def chattr(self, attr: paramiko.SFTPAttributes) -> int:
		try:
			paramiko.SFTPServer.set_file_attr(self.filename, attr)
			return paramiko.SFTP_OK
		except OSError as error:
			return sftp_error(error)

class LocalSftpServer(paramiko.SFTPServerInterface):
	@staticmethod
	def local(path: str) -> str:
		return os.path.normpath(path if os.path.isabs(path) else os.path.join(SERVER_HOME, path))

	@staticmethod
	def call(function: Callable[..., object], *args: object) -> int:
		try:
			function(*args)
			return paramiko.SFTP_OK
		except OSError as error:
			return sftp_error(error)

	def canonicalize(self, path: str) -> str:
		return self.local(path)

	def list_folder(self, path: str) -> list[paramiko.SFTPAttributes] | int:
		folder = self.local(path)
		try:
			names = os.listdir(folder)
		except OSError as error:
			return sftp_error(error)
		entries = []
		for name in names:
			full = os.path.join(folder, name)
			try:
				attributes = paramiko.SFTPAttributes.from_stat(os.stat(full))
			except OSError: # A dangling symlink still deserves its line in the listing
				try:
					attributes = paramiko.SFTPAttributes.from_stat(os.lstat(full))
				except OSError:
					continue
			attributes.filename = name
			entries.append(attributes)
		return entries

	def stat(self, path: str) -> paramiko.SFTPAttributes | int:
		try:
			return paramiko.SFTPAttributes.from_stat(os.stat(self.local(path)))
		except OSError as error:
			return sftp_error(error)

	def lstat(self, path: str) -> paramiko.SFTPAttributes | int:
		try:
			return paramiko.SFTPAttributes.from_stat(os.lstat(self.local(path)))
		except OSError as error:
			return sftp_error(error)

	def open(self, path: str, flags: int, attr: paramiko.SFTPAttributes | None) -> LocalSftpHandle | int:
		local_path = self.local(path)
		mode = getattr(attr, "st_mode", None)
		try:
			fd = os.open(local_path, flags, mode if mode is not None else 0o666)
		except OSError as error:
			return sftp_error(error)
		if flags & os.O_CREAT and attr is not None:
			attr._flags &= ~attr.FLAG_PERMISSIONS # os.open already applied the mode
			try:
				paramiko.SFTPServer.set_file_attr(local_path, attr)
			except OSError:
				pass # e.g. a timestamp the FUSE storage refuses - not worth failing the upload over
		if flags & os.O_WRONLY:
			file_mode = "ab" if flags & os.O_APPEND else "wb"
		elif flags & os.O_RDWR:
			file_mode = "a+b" if flags & os.O_APPEND else "r+b"
		else:
			file_mode = "rb"
		file = os.fdopen(fd, file_mode)
		handle = LocalSftpHandle(flags)
		handle.filename = local_path
		handle.readfile = file
		handle.writefile = file
		return handle

	def remove(self, path: str) -> int:
		return self.call(os.remove, self.local(path))

	def rename(self, oldpath: str, newpath: str) -> int:
		return self.call(os.rename, self.local(oldpath), self.local(newpath))

	def posix_rename(self, oldpath: str, newpath: str) -> int:
		return self.call(os.replace, self.local(oldpath), self.local(newpath))

	def mkdir(self, path: str, attr: paramiko.SFTPAttributes) -> int:
		return self.call(os.mkdir, self.local(path))

	def rmdir(self, path: str) -> int:
		return self.call(os.rmdir, self.local(path))

	def chattr(self, path: str, attr: paramiko.SFTPAttributes) -> int:
		return self.call(paramiko.SFTPServer.set_file_attr, self.local(path), attr)

	def symlink(self, target_path: str, path: str) -> int:
		return self.call(os.symlink, target_path, self.local(path))

	def readlink(self, path: str) -> str | int:
		try:
			return os.readlink(self.local(path))
		except OSError as error:
			return sftp_error(error)
#endregion

#* accepting connections

def handle_connection(client: socket.socket, address: tuple[str, int], host_key: paramiko.PKey) -> None:
	log(f"connection from {address[0]}:{address[1]}")
	transport = paramiko.Transport(client)
	transport.add_server_key(host_key)
	transport.set_subsystem_handler("sftp", paramiko.SFTPServer, LocalSftpServer)
	try:
		transport.start_server(server=Server(load_authorized_keys()))
	except (paramiko.SSHException, EOFError, OSError) as error:
		logger.error(f"  handshake with {address[0]}:{address[1]} failed: {error!r}")
		transport.close()
		return
	transport.join() # Channels are served from the transport's own thread; this one only waits for it
	log(f"disconnected {address[0]}:{address[1]}")

def lan_address() -> str | None:
	"""Best effort, for the startup banner: the address this device uses on the LAN."""
	try:
		with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
			probe.connect(("192.168.0.1", 9)) # UDP connect sends nothing, it only picks a route
			return probe.getsockname()[0]
	except OSError:
		return None

def main() -> None:
	ensureFolderExists(SERVER_HOME)
	setup_logging()
	log(f"--- starting, log file {LOG_FILE}")
	writeTextFile(SHELL_RC_FILE, shell_prelude())
	host_key = load_or_create_host_key()
	log(f"python {sys.version.split()[0]} at {sys.executable}, paramiko {paramiko.__version__}")
	log(f"home {SERVER_HOME}, shell {SHELL}, uid {os.getuid()}")
	log(f"host key {host_key.get_name()} {host_key.get_fingerprint().hex(':')}")
	log(f"{len(load_authorized_keys())} authorized key(s)")

	with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
		server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
		try:
			server.bind((LISTEN_ADDRESS, PORT))
		except OSError as error:
			if error.errno == errno.EADDRINUSE:
				raise SimpleError(f"port {PORT} is already taken - is a previous ssh-server.py still running?", None) from error
			raise
		server.listen(16)
		addresses = ", ".join(address for address in (lan_address(), "127.0.0.1") if address)
		log(f"listening on port {PORT} ({addresses}) - stop the script to quit")
		while True:
			client, address = server.accept()
			threading.Thread(target=handle_connection, args=(client, address, host_key), daemon=True).start()

if __name__ == "__main__":
	try:
		main()
	except KeyboardInterrupt:
		log("stopped")
	except SimpleError as error: # An expected failure - its message says it all, no traceback
		logger.critical(f"server stopped: {error}")
		raise SystemExit(1)
	except Exception:
		logger.critical("server crashed", exc_info=True)
		raise SystemExit(1)
