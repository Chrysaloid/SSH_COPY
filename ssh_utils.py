from pathlib import Path as _Path; __package__ = __package__ or _Path(__file__).resolve().parent.name # To be able to use relative imports when run directly - never override a __package__ Python already set (see README)

import base64 as _base64
from collections.abc import Callable as _Callable, Sequence as _Sequence
from enum import auto, IntEnum
from functools import partial as _partial
import logging as _logging
import queue as _queue
import re as _re
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

from .common_constants import COLOR_ERROR as _COLOR_ERROR
from .file_utils import is_dir as _is_dir, is_file as _is_file, iterate_path_parts as _iterate_path_parts
from .local_sftp_attributes import Local_SFTPAttributes as _Local_SFTPAttributes
from .simple_error import Simple_error as _Simple_error

class Os(IntEnum):
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
		raise _Simple_error(f"Invalid host format: {host}. Should be user@192.168.0.123:1234")

	try:
		hostname, port = rest.split(":")
	except ValueError:
		raise _Simple_error(f"Invalid host format: {host}. Should be user@192.168.0.123:1234")

	try:
		port = int(port)
	except ValueError:
		raise _Simple_error(f"Invalid host format: {host}. Port should be int, you typed '{port}'")

	return user, hostname, port

def parse_host_key(host_key: str) -> _paramiko.PKey:
	""" A public key as sshd's ssh_host_*_key.pub holds it: "ssh-ed25519 AAAA..." (a trailing comment is ignored) """
	try:
		key_type, blob = host_key.split()[:2]
		return _paramiko.PKey.from_type_string(key_type, _base64.b64decode(blob))
	except Exception as e:
		raise _Simple_error(f'Invalid host key "{host_key[:40]}...": {e}. Should be "ssh-ed25519 AAAA..."')

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
	sock: _socket.socket | None = None,
) -> tuple[str | None, bool]:
	"""
	One login attempt. Returns (error_message, address_is_dead) - error_message None means ssh is
	connected. sock is a TCP connection to hostname:port made beforehand (see _open_socket);
	paramiko then logs in over it instead of connecting by itself.
	"""
	error_message = None
	address_is_dead = False
	if pinned_keys:
		# paramiko looks keys up under the same name it would use in known_hosts
		key_name = hostname if port == 22 else f"[{hostname}]:{port}"
		for pinned_key in pinned_keys:
			ssh.get_host_keys().add(key_name, pinned_key.get_name(), pinned_key)

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
			sock         = sock        ,
		)
	except _BadHostKeyException as e:
		address_is_dead = True
		error_message = f"ERROR: {hostname}:{port} presented host key {e.key.fingerprint}, not the pinned {e.expected_key.fingerprint} - a different machine, skipped before logging in"
	except _AuthenticationException:
		error_message = f"ERROR: Authentication failed when connecting to {hostname}"
	except _PartialAuthentication:
		error_message = f"ERROR: Partial authentication occurred when connecting to {hostname}"
	except _NoValidConnectionsError:
		address_is_dead = True
		error_message = f"ERROR: No valid connections could be made to {hostname} (connection refused or unreachable)"
	except _PasswordRequiredException:
		error_message = f"ERROR: The private key is encrypted and requires a passphrase"
	except _BadAuthenticationType as e:
		error_message = f"ERROR: Unsupported authentication type. Allowed types: {", ".join(e.allowed_types)}"
	except _ProxyCommandFailure as e:
		error_message = f"ERROR: Proxy command failed: {e}"
	except FileNotFoundError as e:
		error_message = f"ERROR: SSH key file not found: {e.filename}"
	except _socket.timeout | TimeoutError:
		address_is_dead = True
		error_message = f"ERROR: Connection to {hostname} timed out after {timeout} seconds"
	except _ChannelException as e:
		error_message = f"ERROR: Failed to open an SSH channel while connecting to {hostname} (channel {e.code}: {e.text})"
	except _ConfigParseError:
		error_message = f"ERROR: Failed to parse the SSH configuration file"
	except _CouldNotCanonicalize:
		error_message = f"ERROR: Failed to canonicalize the hostname {hostname}"
	except _IncompatiblePeer:
		error_message = f"ERROR: SSH negotiation failed because {hostname} is incompatible with this SSH client"
	except _MessageOrderError:
		error_message = f"ERROR: Invalid SSH message order was received from {hostname}"
	except _SSHException as e:
		msg = str(e)
		if "No authentication method" in msg:
			error_message = f"ERROR: No authentication method available. No password was supplied and no usable SSH keys were found"
		else:
			error_message = f"ERROR: SSH error while connecting to {hostname}: {msg}"
	except _socket.error as e:
		address_is_dead = True
		error_message = f"ERROR: Socket error while connecting to {hostname}: {e}"

	if error_message is not None:
		# A failed login (e.g. the wrong user) leaves its transport open, and the next connect()
		# on this client would just drop the reference to it - a live connection leaked per failure.
		# Closing keeps the client reusable, host keys included.
		ssh.close()
		if sock is not None:
			sock.close() # paramiko may have failed before its transport took the socket over

	return error_message, address_is_dead

def _open_socket(hostname: str, port: int, timeout: float) -> tuple[_socket.socket | None, str | None]:
	""" A TCP connection to hostname:port, or None and the error _connect_once would have reported for it """
	try:
		return _socket.create_connection((hostname, port), timeout=timeout), None
	except TimeoutError:
		return None, f"ERROR: Connection to {hostname} timed out after {timeout} seconds"
	except _socket.gaierror as e:
		return None, f"ERROR: Socket error while connecting to {hostname}: {e}"
	except OSError:
		return None, f"ERROR: No valid connections could be made to {hostname} (connection refused or unreachable)"

# How long an address that has its TCP connection waits for the one connected before it to log in.
# Two SSH handshakes at once cost both of them: to this PC's own sshd, racing two of its addresses
# took 396 ms against 218 ms for one (2026-10-25) - the key exchanges share this process (and there
# the CPU with sshd). Past the head start, a handshake that hangs no longer holds the others up.
HANDSHAKE_HEAD_START_SECONDS = 1.0

def _connect_in_parallel(
	options: dict[tuple[str, int], list[str]],
	attempt: _Callable[..., tuple[str | None, bool]],
	pinned_keys: list[_paramiko.PKey] | None,
	timeout: float,
	silent: bool,
) -> tuple[_paramiko.SSHClient | None, bool]:
	"""
	Tries every address at once, one daemon thread each, going through its usernames in order.
	Returns the first client that logs in (None if none did) and whether an error was printed
	before that.

	Only the TCP connections race freely. The SSH handshakes then go one at a time, in the order
	the connections were made - so the fastest address logs in alone, unslowed by the others -
	except that one taking longer than HANDSHAKE_HEAD_START_SECONDS lets the next one start
	beside it. Once one has logged in, the others close their connections without logging in.
	The losing threads are left to finish on their own and nothing they hit afterwards is
	printed. Daemon threads, so a connect still hanging in one of them never holds up the
	interpreter's exit.
	"""
	results: _queue.SimpleQueue[_paramiko.SSHClient | Exception | None] = _queue.SimpleQueue()
	lock = _threading.Lock() # makes "who won" and every print after it one decision
	won = _threading.Event()
	handshake_turn = _threading.Lock()
	there_was_ssh_error = False

	def try_address(hostname: str, port: int, usernames: list[str]) -> None:
		nonlocal there_was_ssh_error
		ssh = _new_ssh_client(pinned_keys)
		outcome: _paramiko.SSHClient | Exception | None = None
		try:
			for i, username in enumerate(usernames):
				if won.is_set():
					break
				sock, error_message = _open_socket(hostname, port, timeout)
				address_is_dead = sock is None
				if sock is not None:
					has_turn = handshake_turn.acquire(timeout=HANDSHAKE_HEAD_START_SECONDS)
					try:
						if won.is_set():
							sock.close()
							break
						error_message, address_is_dead = attempt(ssh, username, hostname, port, sock=sock)
					finally:
						if has_turn:
							handshake_turn.release()
				with lock:
					if won.is_set():
						break # the caller already has its connection - stay quiet
					if error_message is None:
						won.set()
						outcome = ssh
						break
					there_was_ssh_error = True
					_cprint(error_message, _COLOR_ERROR)
					if address_is_dead:
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
		_threading.Thread(target=try_address, args=(hostname, port, usernames), name=f"get_ssh {hostname}:{port}", daemon=True).start()

	first_exception: Exception | None = None
	for _ in options:
		while True:
			try:
				outcome = results.get(timeout=0.1) # a get() with no timeout cannot be interrupted by Ctrl+C on Windows
				break
			except _queue.Empty:
				pass
		if isinstance(outcome, _paramiko.SSHClient):
			with lock:
				return outcome, there_was_ssh_error
		if isinstance(outcome, Exception) and first_exception is None:
			first_exception = outcome

	if first_exception is not None:
		raise first_exception
	return None, there_was_ssh_error

def get_ssh(
	username: str,
	hostnames: str | list[str],
	password: str = None,
	hosts: str | list[str] = None,
	key_filename: str = None,
	timeout: float = 5,
	port = 22,
	silent = False,
	host_keys: str | list[str] | None = None,
	parallel_connect: bool = True,
) -> tuple[_paramiko.SSHClient, bool]:
	"""
	Connect to the first of hosts (user@host:port) - or of hostnames, all with username and
	port - that lets us in. The list is a fallback for CONNECTING only.

	host_keys pins the machine: its public sshd host keys, as in ssh_host_*_key.pub. Every
	address is then checked against them before logging in, and one presenting any other key
	is rejected and the next tried - so an address that means a different machine on another
	network (192.168.0.x at home vs at a friend's) is safe to keep in the list. Pin an
	ed25519 key: paramiko asks the server for the first pinned key's type, and asking a modern
	OpenSSH for plain "ssh-rsa" (SHA-1) can fail the handshake. Without host_keys any key is
	accepted, as before.

	An address that timed out, refused, or presented the wrong key is not tried again with
	the next user - only an authentication failure moves on to another user at the same address.

	parallel_connect tries all addresses (hostname+port) at once instead of one by one, each
	going through its users in the order given, and returns the first client that logs in -
	still synchronously. Only the TCP connections race: the logins follow one at a time in the
	order the connections came, each with a head start before the next one joins in (see
	_connect_in_parallel), so a second working address costs the winner nothing. Errors the
	other addresses hit after that are not printed. With only one address there is nothing to
	race, so the hosts are then tried one by one regardless.
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

	pinned_keys = None
	if host_keys:
		if isinstance(host_keys, str):
			host_keys = [host_keys]
		pinned_keys = [parse_host_key(host_key) for host_key in host_keys]

	if hosts:
		if isinstance(hosts, str):
			hosts = [hosts]

		hosts = tuple(map(parse_host, hosts))
	else:
		if isinstance(hostnames, str):
			hostnames = [hostnames]

		hosts = tuple(zip([username] * len(hostnames), hostnames, [port] * len(hostnames)))

	if not hosts:
		raise _Simple_error("hosts cannot be empty")

	attempt = _partial(_connect_once, password=password, key_filename=key_filename, timeout=timeout, silent=silent, pinned_keys=pinned_keys)

	options: dict[tuple[str, int], list[str]] = {} # (hostname, port) -> its usernames in the order they came
	for username, hostname, port in hosts:
		options.setdefault((hostname, port), []).append(username)

	parallel_connect = parallel_connect and len(options) > 1
	if parallel_connect:
		ssh, there_was_ssh_error = _connect_in_parallel(options, attempt, pinned_keys, timeout, silent)
		if ssh is None:
			raise _Simple_error("", None)
		return ssh, there_was_ssh_error

	ssh = _new_ssh_client(pinned_keys)
	there_was_ssh_error = False
	connected = False
	dead_addresses: set[tuple[str, int]] = set() # timed out, refused or the wrong machine - no other user will fare better
	for username, hostname, port in hosts:
		if (hostname, port) in dead_addresses:
			if not silent:
				print(f"Skipping {username}@{hostname}:{port} - that address already failed")
			continue

		error_message, address_is_dead = attempt(ssh, username, hostname, port)
		if error_message is None:
			connected = True
			break

		there_was_ssh_error = True
		_cprint(error_message, _COLOR_ERROR)
		if address_is_dead:
			dead_addresses.add((hostname, port))

	# Not "if error_message": a skipped last entry leaves it None although nothing connected
	if not connected:
		raise _Simple_error("", None)

	return ssh, there_was_ssh_error

def get_output_of_remote_command(ssh: _paramiko.SSHClient, command: str) -> str:
	""" Runs a command remotely and returns its stripped, lowercased stdout ("" if anything went wrong) """
	try:
		stdin, stdout, stderr = ssh.exec_command(command)
		return stdout.read().decode(errors="ignore").strip().lower()
	except Exception:
		return ""

def detect_remote_os(ssh: _paramiko.SSHClient) -> Os:
	try:
		banner = ssh.get_transport().remote_version.lower()
		if "windows" in banner: # Win32-OpenSSH announces itself as "OpenSSH_for_Windows_<version>"
			return Os.WINDOWS
	except Exception:
		pass

	kernel = get_output_of_remote_command(ssh, "uname -s")
	if kernel:
		if kernel.startswith("darwin"):
			return Os.MAC
		if kernel.startswith(("msys_nt", "cygwin_nt", "mingw")): # A POSIX layer running on top of Windows
			return Os.WINDOWS
		if kernel.startswith("linux"):
			# Android's kernel name is "Linux" too, so it has to be told apart by other means:
			# "uname -o" prints "Android" (instead of "GNU/Linux"), Termux exports $PREFIX
			# (/data/data/com.termux/files/usr) and $TERMUX_VERSION and every Android exports $ANDROID_ROOT
			flavour = get_output_of_remote_command(ssh, 'echo "$(uname -o 2>/dev/null) $PREFIX$TERMUX_VERSION $ANDROID_ROOT$ANDROID_DATA"')
			if "termux" in flavour:
				return Os.TERMUX
			if "android" in flavour:
				return Os.ANDROID

			return Os.LINUX

		return Os.LINUX # Unexpected uname string -> treat as some other POSIX system

	# Fallback: try cmd.exe (may also work in WSL, so only used if uname is absent)
	if get_output_of_remote_command(ssh, "cmd.exe /c echo %OS%").startswith("windows"):
		return Os.WINDOWS

	raise _Simple_error(f"Could not determine remote OS due to errors") # Should not happen?

def is_folder_case_sensitive(ssh: _paramiko.SSHClient, path_to_folder: str) -> bool:
	stdin, stdout, stderr = ssh.exec_command(f'C:/Windows/System32/fsutil.exe file queryCaseSensitiveInfo "{path_to_folder}" 2>&1')
	output = stdout.read().decode(errors="ignore")
	output_processed = output.strip().lower()

	if output_processed.endswith("enabled."):
		return True
	if output_processed.endswith("disabled."):
		return False

	raise RuntimeError(f"Unexpected fsutil output:\n{output}")

def remote_file_exists(sftp: _paramiko.SFTPClient, remote_path: str) -> bool:
	try:
		file_info = sftp.stat(remote_path) # Raises FileNotFoundError if it doesn't exist
		return _is_file(file_info)
	except FileNotFoundError:
		return False

def remote_folder_exists(sftp: _paramiko.SFTPClient, remote_path: str) -> bool:
	try:
		file_info = sftp.stat(remote_path) # Raises FileNotFoundError if it doesn't exist
		return _is_dir(file_info)
	except FileNotFoundError:
		return False

def assert_remote_folder_exists(sftp: _paramiko.SFTPClient, remote_path: str, additional_comment = ""):
	if not remote_folder_exists(sftp, remote_path):
		raise _Simple_error(f'The remote folder "{remote_path}" does not exist or is not a folder{additional_comment}')

def remote_mkdir(sftp: _paramiko.SFTPClient, remote_path: str):
	""" Returns True if folder was created and False if it already exists """
	try:
		sftp.mkdir(remote_path)
		return True
	except IOError:
		return False

def ensure_remote_folder_exists(sftp: _paramiko.SFTPClient, remote_path: str):
	""" Returns True if any part folder was created and False if it already exists """
	created = False
	if not remote_folder_exists(sftp, remote_path):
		for part in _iterate_path_parts(remote_path):
			created = remote_mkdir(sftp, part) or created
	return created

class Remote_list_dir:
	def __init__(self, ssh: _paramiko.SSHClient, python_str = "python", init = False, follow_symlinks = False):
		self.ssh = ssh
		self.python_str = python_str
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
			cmd = f'{self.python_str} -c "exec(\\\"{code}\\\")"'
			self.stdin, self.stdout, self.stderr = self.ssh.exec_command(cmd)

	def listdir_attr(self, path: str):
		self.init()

		try:
			self.stdin.write(path + "\n")
			self.stdin.flush()
		except OSError: # Socket is closed (probably because remote python crashed because the scanned folder was inaccessible because script did not have suficent permissions)
			self.stdin = None # reset stdin so the remote script gets recreated on the next use # TODO find a better solution for this
			raise _Simple_error(
				f'Remote_list_dir.listdir_attr: remote script returned error when listing folder "{path}":\n{ \
				self.stderr.read().decode(errors="ignore").strip() \
				or self.stdout.read().decode(errors="ignore").strip()}'
			)

		entries = []
		while (line := self.stdout.readline().rstrip()):
			filename, st_mode, st_size, st_atime, st_mtime = line.split("/")
			entries.append(_Local_SFTPAttributes.from_values(
				filename=filename,
				st_mode =int(st_mode , 16),
				st_size =int(st_size , 16),
				st_atime=int(st_atime, 16),
				st_mtime=int(st_mtime, 16),
			))
		return entries

_DOTTED_VERSION = _re.compile(r"\d+(?:\.\d+)+")
_BARE_VERSION   = _re.compile(r"\d+")

def _find_version(outputs: list[str]) -> str:
	""" The first dotted number in any of the outputs, else the first bare one, else "" """
	for pattern in (_DOTTED_VERSION, _BARE_VERSION):
		for output in outputs:
			if match := pattern.search(output):
				return match.group()
	return ""

def version_matches(version: str, expected_version: str) -> bool:
	""" Whether version is expected_version or one of its sub-versions: "3.13.5" matches "3" and "3.13", not "3.1" """
	return not expected_version or version == expected_version or version.startswith(expected_version + ".")

def remote_has_program(
	ssh: _paramiko.SSHClient,
	candidates: str | _Sequence[str],
	expected_version: str = "",
	version_argument: str = "--version",
	throw_on_not_found: bool = True,
) -> tuple[str, str]:
	"""
	The first of candidates that runs on the remote as `<candidate> <version_argument>`, exits 0
	and reports a version matching expected_version (see version_matches; "" takes any), together
	with that version: ("python3", "3.12.3"). The version is the first dotted number of stdout,
	else of stderr, else the first bare number - "Python 3.12.3", "v22.11.0", "GNU bash, version
	5.2.37(1)" and "PowerShell 7.6.6" all work, and Python 2 printed its version to stderr. A candidate is
	put on the command line as is, so it may be a full path, quoted for the remote shell.

	Windows PowerShell 5.1 has no --version: give it version_argument
	"-NoProfile -Command $PSVersionTable.PSVersion.ToString()".

	Raises Simple_error when none qualifies, or returns ("", "") with throw_on_not_found=False.
	"""
	if isinstance(candidates, str):
		candidates = [candidates]

	for candidate in candidates:
		stdin, stdout, stderr = ssh.exec_command(f"{candidate} {version_argument}")
		stdin.close()
		# stdout first: WSL's bash.exe puts a systemd warning on stderr, and Python 2 its version
		outputs = [stream.read().decode(errors="ignore") for stream in (stdout, stderr)]
		# A missing program exits non-zero everywhere - and the Windows Store "python" stub prints
		# its install-me message with 9009
		if stdout.channel.recv_exit_status() != 0:
			continue
		if (version := _find_version(outputs)) and version_matches(version, expected_version):
			return candidate, version

	if throw_on_not_found:
		wanted = f" {expected_version}" if expected_version else ""
		raise _Simple_error(f"None of {', '.join(candidates)}{wanted} found remotely")
	return "", ""

def remote_has_python(ssh: _paramiko.SSHClient, throw_on_not_found: bool = True, enforce_python_ver: str = "3") -> str:
	"""
	Returns python alias that worked.
	You can pass empty str as enforce_python_ver to not enforce version.
	"""
	try:
		return remote_has_program(ssh, ("python", "python3", "py"), enforce_python_ver, throw_on_not_found=throw_on_not_found)[0]
	except _Simple_error:
		raise _Simple_error(f"No Python found remotely") from None

if __name__ == "__main__": # Example usage
	from my_libs.ssh_utils import get_ssh
	ssh, there_was_ssh_error = get_ssh(
		username  = "Test"         ,
		hostnames = "192.168.0.121",
		password  = None           ,
	)
	sftp = ssh.open_sftp()

	print(remote_folder_exists(sftp, "G:/temp"))
	print(remote_folder_exists(sftp, "G:/temp/"))
	print()

	print(Os.WINDOWS)
	print(Os.LINUX)

def parse_os_str(os_str: str | Os, ssh: _paramiko.SSHClient) -> Os:
	""" Parse (or detect remote) OS """
	if isinstance(os_str, Os): return os_str # an OS member is an instance, not a class - issubclass would raise
	match os_str.lower().strip():
		case "w" | "win" | "windows"                     : return Os.WINDOWS
		case "u" | "unix" | "l" | "linux" | "p" | "posix": return Os.LINUX
		case "m" | "mac" | "macos" | "darwin"            : return Os.MAC
		case "t" | "termux"                              : return Os.TERMUX
		case "n" | "android"                             : return Os.ANDROID
		case "a" | "auto" | "auto-detect"                : return detect_remote_os(ssh) if ssh else Os.UNKNOWN
		case _: raise _Simple_error(f"Invalid OS: {os_str}")
