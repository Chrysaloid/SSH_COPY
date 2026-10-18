from pathlib import Path as _Path; __package__ = __package__ or _Path(__file__).resolve().parent.name # To be able to use relative imports when run directly - never override a __package__ Python already set (see README)

import base64 as _base64
from collections.abc import Callable as _Callable
from enum import auto, IntEnum
from functools import partial as _partial
import logging as _logging
import queue as _queue
import socket as _socket
import threading as _threading

import paramiko as _paramiko
from paramiko.ssh_exception import (
	AuthenticationException as _AuthenticationException,
	BadAuthenticationType as _BadAuthenticationType,
	BadHostKeyException as _BadHostKeyException,
	ChannelException as _ChannelException,
	ConfigParseError as _ConfigParseError,
	CouldNotCanonicalize as _CouldNotCanonicalize,
	IncompatiblePeer as _IncompatiblePeer,
	MessageOrderError as _MessageOrderError,
	NoValidConnectionsError as _NoValidConnectionsError,
	PartialAuthentication as _PartialAuthentication,
	PasswordRequiredException as _PasswordRequiredException,
	ProxyCommandFailure as _ProxyCommandFailure,
	SSHException as _SSHException
)
from termcolor import colored as _clr, cprint as _cprint

from .commonConstants import COLOR_ERROR as _COLOR_ERROR
from .fileUtils import isDir as _isDir, isFile as _isFile, iteratePathParts as _iteratePathParts
from .LocalSFTPAttributes import LocalSFTPAttributes as _LocalSFTPAttributes
from .SimpleError import SimpleError as _SimpleError

class OS(IntEnum):
	WINDOWS = auto(1)
	LINUX   = auto()
	TERMUX  = auto()
	ANDROID = auto() # Android without Termux (paths are not rooted in /data/data/com.termux/files)
	MAC     = auto()
	UNKNOWN = auto()

def parse_host(host: str) -> tuple[str, str, int]:
	try:
		user, rest = host.split("@")
	except ValueError:
		raise _SimpleError(f"Invalid host format: {host}. Should be user@192.168.0.123:1234")

	try:
		hostname, port = rest.split(":")
	except ValueError:
		raise _SimpleError(f"Invalid host format: {host}. Should be user@192.168.0.123:1234")

	try:
		port = int(port)
	except ValueError:
		raise _SimpleError(f"Invalid host format: {host}. Port should be int, you typed '{port}'")

	return user, hostname, port

def parseHostKey(hostKey: str) -> _paramiko.PKey:
	""" A public key as sshd's ssh_host_*_key.pub holds it: "ssh-ed25519 AAAA..." (a trailing comment is ignored) """
	try:
		keyType, blob = hostKey.split()[:2]
		return _paramiko.PKey.from_type_string(keyType, _base64.b64decode(blob))
	except Exception as e:
		raise _SimpleError(f'Invalid host key "{hostKey[:40]}...": {e}. Should be "ssh-ed25519 AAAA..."')

def _new_ssh_client(pinned_keys: list[_paramiko.PKey] | None) -> _paramiko.SSHClient:
	ssh = _paramiko.SSHClient()
	# With pinned keys every address gets them registered before connecting, so the policy is never asked;
	# RejectPolicy only makes sure an address that somehow slipped past would fail, not be trusted.
	ssh.set_missing_host_key_policy(_paramiko.RejectPolicy() if pinned_keys else _paramiko.AutoAddPolicy())
	return ssh

def _connect_once(
	ssh: _paramiko.SSHClient,
	username: str,
	hostname: str,
	port: int,
	*,
	password: str | None,
	key_filename: str | None,
	timeout: float,
	silent: bool,
	pinned_keys: list[_paramiko.PKey] | None,
) -> tuple[str | None, bool]:
	""" One login attempt. Returns (errorMessage, addressIsDead) - errorMessage None means ssh is connected """
	errorMessage = None
	addressIsDead = False
	if pinned_keys:
		# paramiko looks keys up under the same name it would use in known_hosts
		keyName = hostname if port == 22 else f"[{hostname}]:{port}"
		for pinnedKey in pinned_keys:
			ssh.get_host_keys().add(keyName, pinnedKey.get_name(), pinnedKey)

	try:
		if not silent:
			print(f"Attempting to connect to {_clr(username, 'green')}@{_clr(hostname, 'green')}:{_clr(port, 'green')} ...")
		ssh.connect(
			hostname     = hostname    ,
			username     = username    ,
			password     = password    ,
			key_filename = key_filename,
			timeout      = timeout     ,
			port         = port        ,
		)
	except _BadHostKeyException as e:
		addressIsDead = True
		errorMessage = f"ERROR: {hostname}:{port} presented host key {e.key.fingerprint}, not the pinned {e.expected_key.fingerprint} - a different machine, skipped before logging in"
	except _AuthenticationException:
		errorMessage = f"ERROR: Authentication failed when connecting to {hostname}"
	except _PartialAuthentication:
		errorMessage = f"ERROR: Partial authentication occurred when connecting to {hostname}"
	except _NoValidConnectionsError:
		addressIsDead = True
		errorMessage = f"ERROR: No valid connections could be made to {hostname} (connection refused or unreachable)"
	except _PasswordRequiredException:
		errorMessage = f"ERROR: The private key is encrypted and requires a passphrase"
	except _BadAuthenticationType as e:
		errorMessage = f"ERROR: Unsupported authentication type. Allowed types: {", ".join(e.allowed_types)}"
	except _ProxyCommandFailure as e:
		errorMessage = f"ERROR: Proxy command failed: {e}"
	except FileNotFoundError as e:
		errorMessage = f"ERROR: SSH key file not found: {e.filename}"
	except _socket.timeout | TimeoutError:
		addressIsDead = True
		errorMessage = f"ERROR: Connection to {hostname} timed out after {timeout} seconds"
	except _ChannelException as e:
		errorMessage = f"ERROR: Failed to open an SSH channel while connecting to {hostname} (channel {e.code}: {e.text})"
	except _ConfigParseError:
		errorMessage = f"ERROR: Failed to parse the SSH configuration file"
	except _CouldNotCanonicalize:
		errorMessage = f"ERROR: Failed to canonicalize the hostname {hostname}"
	except _IncompatiblePeer:
		errorMessage = f"ERROR: SSH negotiation failed because {hostname} is incompatible with this SSH client"
	except _MessageOrderError:
		errorMessage = f"ERROR: Invalid SSH message order was received from {hostname}"
	except _SSHException as e:
		msg = str(e)
		if "No authentication method" in msg:
			errorMessage = f"ERROR: No authentication method available. No password was supplied and no usable SSH keys were found"
		else:
			errorMessage = f"ERROR: SSH error while connecting to {hostname}: {msg}"
	except _socket.error as e:
		addressIsDead = True
		errorMessage = f"ERROR: Socket error while connecting to {hostname}: {e}"

	if errorMessage is not None:
		# A failed login (e.g. the wrong user) leaves its transport open, and the next connect()
		# on this client would just drop the reference to it - a live connection leaked per failure.
		# Closing keeps the client reusable, host keys included.
		ssh.close()

	return errorMessage, addressIsDead

def _connect_in_parallel(
	options: dict[tuple[str, int], list[str]],
	attempt: _Callable[[_paramiko.SSHClient, str, str, int], tuple[str | None, bool]],
	pinned_keys: list[_paramiko.PKey] | None,
	silent: bool,
) -> tuple[_paramiko.SSHClient | None, bool]:
	"""
	Tries every address at once, one daemon thread each, going through its usernames in order.
	Returns the first client that logs in (None if none did) and whether an error was printed
	before that. The losing threads are left to finish on their own: one that still logs in
	closes its client, and nothing they hit afterwards is printed. Daemon threads, so a
	connect still hanging in one of them never holds up the interpreter's exit.
	"""
	results: _queue.SimpleQueue[_paramiko.SSHClient | Exception | None] = _queue.SimpleQueue()
	lock = _threading.Lock() # makes "who won" and every print after it one decision
	won = _threading.Event()
	there_was_SSH_error = False

	def try_address(hostname: str, port: int, usernames: list[str]) -> None:
		nonlocal there_was_SSH_error
		ssh = _new_ssh_client(pinned_keys)
		outcome: _paramiko.SSHClient | Exception | None = None
		try:
			for i, username in enumerate(usernames):
				if won.is_set():
					break
				errorMessage, addressIsDead = attempt(ssh, username, hostname, port)
				with lock:
					if won.is_set():
						break # the caller already has its connection - stay quiet
					if errorMessage is None:
						won.set()
						outcome = ssh
						break
					there_was_SSH_error = True
					_cprint(errorMessage, _COLOR_ERROR)
					if addressIsDead:
						if not silent:
							for skipped in usernames[i + 1:]:
								print(f"Skipping {skipped}@{hostname}:{port} - that address already failed")
						break
		except Exception as e: # not a connection failure (those are all handled in _connect_once) - the caller gets it if nobody connects
			outcome = e
		finally:
			if outcome is not ssh:
				ssh.close()
			results.put(outcome)

	for (hostname, port), usernames in options.items():
		_threading.Thread(target=try_address, args=(hostname, port, usernames), name=f"getSSH {hostname}:{port}", daemon=True).start()

	firstException: Exception | None = None
	for _ in options:
		while True:
			try:
				outcome = results.get(timeout=0.1) # a get() with no timeout cannot be interrupted by Ctrl+C on Windows
				break
			except _queue.Empty:
				pass
		if isinstance(outcome, _paramiko.SSHClient):
			with lock:
				return outcome, there_was_SSH_error
		if isinstance(outcome, Exception) and firstException is None:
			firstException = outcome

	if firstException is not None:
		raise firstException
	return None, there_was_SSH_error

def getSSH(
	username: str,
	hostnames: str | list[str],
	password: str = None,
	hosts: str | list[str] = None,
	keyFilename: str = None,
	timeout: float = 5,
	port = 22,
	silent = False,
	hostKeys: str | list[str] | None = None,
	parallel_connect: bool = True,
) -> tuple[_paramiko.SSHClient, bool]:
	"""
	Connect to the first of hosts (user@host:port) - or of hostnames, all with username and
	port - that lets us in. The list is a fallback for CONNECTING only.

	hostKeys pins the machine: its public sshd host keys, as in ssh_host_*_key.pub. Every
	address is then checked against them before logging in, and one presenting any other key
	is rejected and the next tried - so an address that means a different machine on another
	network (192.168.0.x at home vs at a friend's) is safe to keep in the list. Pin an
	ed25519 key: paramiko asks the server for the first pinned key's type, and asking a modern
	OpenSSH for plain "ssh-rsa" (SHA-1) can fail the handshake. Without hostKeys any key is
	accepted, as before.

	An address that timed out, refused, or presented the wrong key is not tried again with
	the next user - only an authentication failure moves on to another user at the same address.

	parallel_connect tries all addresses (hostname+port) at once instead of one by one, each
	going through its users in the order given, and returns the first client that logs in -
	still synchronously. Errors the other addresses hit after that are not printed. With only
	one address there is nothing to race, so the hosts are then tried one by one regardless.
	"""
	# paramiko reports a failed connection twice: as the exception handled below, and through
	# the "paramiko" logger, from its transport thread, as "Exception (client): ..." plus a
	# full traceback. In a program that never configured logging, that second copy lands on
	# stderr via logging's last-resort handler - a wall of traceback in front of our own
	# one-line message, e.g. whenever 127.0.0.1 is an adb forward with no server behind it.
	# A NullHandler stops only that fallback: a program that does configure logging (like
	# ssh-server.py) still gets every paramiko record through propagation.
	paramiko_logger = _logging.getLogger("paramiko")
	if all(not isinstance(handler, _logging.NullHandler) for handler in paramiko_logger.handlers):
		paramiko_logger.addHandler(_logging.NullHandler())

	pinnedKeys = None
	if hostKeys:
		if isinstance(hostKeys, str):
			hostKeys = [hostKeys]
		pinnedKeys = [parseHostKey(hostKey) for hostKey in hostKeys]

	if hosts:
		if isinstance(hosts, str):
			hosts = [hosts]

		hosts = tuple(map(parse_host, hosts))
	else:
		if isinstance(hostnames, str):
			hostnames = [hostnames]

		hosts = tuple(zip([username] * len(hostnames), hostnames, [port] * len(hostnames)))

	if not hosts:
		raise _SimpleError("hosts cannot be empty")

	attempt = _partial(_connect_once, password=password, key_filename=keyFilename, timeout=timeout, silent=silent, pinned_keys=pinnedKeys)

	options: dict[tuple[str, int], list[str]] = {} # (hostname, port) -> its usernames in the order they came
	for username, hostname, port in hosts:
		options.setdefault((hostname, port), []).append(username)

	parallel_connect = parallel_connect and len(options) > 1
	if parallel_connect:
		ssh, there_was_SSH_error = _connect_in_parallel(options, attempt, pinnedKeys, silent)
		if ssh is None:
			raise _SimpleError("", None)
		return ssh, there_was_SSH_error

	ssh = _new_ssh_client(pinnedKeys)
	there_was_SSH_error = False
	connected = False
	deadAddresses: set[tuple[str, int]] = set() # timed out, refused or the wrong machine - no other user will fare better
	for username, hostname, port in hosts:
		if (hostname, port) in deadAddresses:
			if not silent:
				print(f"Skipping {username}@{hostname}:{port} - that address already failed")
			continue

		errorMessage, addressIsDead = attempt(ssh, username, hostname, port)
		if errorMessage is None:
			connected = True
			break

		there_was_SSH_error = True
		_cprint(errorMessage, _COLOR_ERROR)
		if addressIsDead:
			deadAddresses.add((hostname, port))

	# Not "if errorMessage": a skipped last entry leaves it None although nothing connected
	if not connected:
		raise _SimpleError("", None)

	return ssh, there_was_SSH_error

def get_output_of_remote_command(ssh: _paramiko.SSHClient, command: str) -> str:
	""" Runs a command remotely and returns its stripped, lowercased stdout ("" if anything went wrong) """
	try:
		stdin, stdout, stderr = ssh.exec_command(command)
		return stdout.read().decode(errors="ignore").strip().lower()
	except Exception:
		return ""

def detect_remote_os(ssh: _paramiko.SSHClient) -> OS:
	try:
		banner = ssh.get_transport().remote_version.lower()
		if "windows" in banner: # Win32-OpenSSH announces itself as "OpenSSH_for_Windows_<version>"
			return OS.WINDOWS
	except Exception:
		pass

	kernel = get_output_of_remote_command(ssh, "uname -s")
	if kernel:
		if kernel.startswith("darwin"):
			return OS.MAC
		if kernel.startswith(("msys_nt", "cygwin_nt", "mingw")): # A POSIX layer running on top of Windows
			return OS.WINDOWS
		if kernel.startswith("linux"):
			# Android's kernel name is "Linux" too, so it has to be told apart by other means:
			# "uname -o" prints "Android" (instead of "GNU/Linux"), Termux exports $PREFIX
			# (/data/data/com.termux/files/usr) and $TERMUX_VERSION and every Android exports $ANDROID_ROOT
			flavour = get_output_of_remote_command(ssh, 'echo "$(uname -o 2>/dev/null) $PREFIX$TERMUX_VERSION $ANDROID_ROOT$ANDROID_DATA"')
			if "termux" in flavour:
				return OS.TERMUX
			if "android" in flavour:
				return OS.ANDROID

			return OS.LINUX

		return OS.LINUX # Unexpected uname string -> treat as some other POSIX system

	# Fallback: try cmd.exe (may also work in WSL, so only used if uname is absent)
	if get_output_of_remote_command(ssh, "cmd.exe /c echo %OS%").startswith("windows"):
		return OS.WINDOWS

	raise _SimpleError(f"Could not determine remote OS due to errors") # Should not happen?

def isFolderCaseSensitive(ssh: _paramiko.SSHClient, pathToFolder: str) -> bool:
	stdin, stdout, stderr = ssh.exec_command(f'C:/Windows/System32/fsutil.exe file queryCaseSensitiveInfo "{pathToFolder}" 2>&1')
	output = stdout.read().decode(errors="ignore")
	outputProcessed = output.strip().lower()

	if outputProcessed.endswith("enabled."):
		return True
	if outputProcessed.endswith("disabled."):
		return False

	raise RuntimeError(f"Unexpected fsutil output:\n{output}")

def remoteFileExists(sftp: _paramiko.SFTPClient, remotePath: str) -> bool:
	try:
		fileInfo = sftp.stat(remotePath) # Raises FileNotFoundError if it doesn't exist
		return _isFile(fileInfo)
	except FileNotFoundError:
		return False

def remoteFolderExists(sftp: _paramiko.SFTPClient, remotePath: str) -> bool:
	try:
		fileInfo = sftp.stat(remotePath) # Raises FileNotFoundError if it doesn't exist
		return _isDir(fileInfo)
	except FileNotFoundError:
		return False

def assertRemoteFolderExists(sftp: _paramiko.SFTPClient, remotePath: str, additionalComment = ""):
	if not remoteFolderExists(sftp, remotePath):
		raise _SimpleError(f'The remote folder "{remotePath}" does not exist or is not a folder{additionalComment}')

def remoteMkdir(sftp: _paramiko.SFTPClient, remotePath: str):
	""" Returns True if folder was created and False if it already exists """
	try:
		sftp.mkdir(remotePath)
		return True
	except IOError:
		return False

def ensureRemoteFolderExists(sftp: _paramiko.SFTPClient, remotePath: str):
	""" Returns True if any part folder was created and False if it already exists """
	created = False
	if not remoteFolderExists(sftp, remotePath):
		for part in _iteratePathParts(remotePath):
			created = remoteMkdir(sftp, part) or created
	return created

class RemoteListDir:
	def __init__(self, ssh: _paramiko.SSHClient, pythonStr = "python", init = False, follow_symlinks = False):
		self.ssh = ssh
		self.pythonStr = pythonStr
		self.follow_symlinks = str(bool(follow_symlinks))
		self.stdin: _paramiko.ChannelFile | None = None
		self.stdout: _paramiko.ChannelFile | None = None
		self.stderr: _paramiko.ChannelFile | None = None
		if init:
			self.init()

	def init(self):
		if self.stdin is None:
			code = (
				"import os\\n"
				"while (s := input()):\\n"
				"	with os.scandir(s) as d:\\n"
				"		for e in d:\\n"
				f"			i = e.stat(follow_symlinks={self.follow_symlinks}); print(e.name, '%x/%x/%x/%x' % (i.st_mode, i.st_size, int(i.st_atime), int(i.st_mtime)), sep='/')\\n"
				"		print('', flush=1)"
			)
			cmd = f'{self.pythonStr} -c "exec(\\\"{code}\\\")"'
			self.stdin, self.stdout, self.stderr = self.ssh.exec_command(cmd)

	def listdir_attr(self, path: str):
		self.init()

		try:
			self.stdin.write(path + "\n")
			self.stdin.flush()
		except OSError: # Socket is closed (probably because remote python crashed because the scanned folder was inaccessible because script did not have suficent permissions)
			self.stdin = None # reset stdin so the remote script gets recreated on the next use # TODO find a better solution for this
			raise _SimpleError(
				f'RemoteListDir.listdir_attr: remote script returned error when listing folder "{path}":\n{ \
				self.stderr.read().decode(errors="ignore").strip() \
				or self.stdout.read().decode(errors="ignore").strip()}'
			)

		entries = []
		while (line := self.stdout.readline().rstrip()):
			filename, st_mode, st_size, st_atime, st_mtime = line.split("/")
			entries.append(_LocalSFTPAttributes.from_values(
				filename=filename,
				st_mode =int(st_mode , 16),
				st_size =int(st_size , 16),
				st_atime=int(st_atime, 16),
				st_mtime=int(st_mtime, 16),
			))
		return entries

def remoteHasPython(ssh: _paramiko.SSHClient, throwOnNotFound = True, enforcePythonVer = "3") -> str:
	"""
	Returns python alias that worked.
	You can pass empty str as enforcePythonVer to not enforce version.
	"""
	for candidate in ("python", "python3", "py"):
		stdin, stdout, stderr = ssh.exec_command(f"{candidate} --version")
		if stdout.read().decode(errors="ignore").strip().lower().startswith(f"python {enforcePythonVer}"):
			return candidate

	if throwOnNotFound:
		raise _SimpleError(f"No Python found remotely")
	else:
		return ""

if __name__ == "__main__": # Example usage
	from myLibs.sshUtils import getSSH
	ssh, thereWasSSHError = getSSH(
		username  = "Test"         ,
		hostnames = "192.168.0.121",
		password  = None           ,
	)
	sftp = ssh.open_sftp()

	print(remoteFolderExists(sftp, "G:/temp"))
	print(remoteFolderExists(sftp, "G:/temp/"))
	print()

	print(OS.WINDOWS)
	print(OS.LINUX)

def parse_os_str(os_str: str | OS, ssh: _paramiko.SSHClient) -> OS:
	""" Parse (or detect remote) OS """
	if isinstance(os_str, OS): return os_str # an OS member is an instance, not a class - issubclass would raise
	match os_str.lower().strip():
		case "w" | "win" | "windows"                     : return OS.WINDOWS
		case "u" | "unix" | "l" | "linux" | "p" | "posix": return OS.LINUX
		case "m" | "mac" | "macos" | "darwin"            : return OS.MAC
		case "t" | "termux"                              : return OS.TERMUX
		case "n" | "android"                             : return OS.ANDROID
		case "a" | "auto" | "auto-detect"                : return detect_remote_os(ssh) if ssh else OS.UNKNOWN
		case _: raise _SimpleError(f"Invalid OS: {os_str}")
