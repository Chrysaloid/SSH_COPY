from pathlib import Path as _Path; __package__ = __package__ or _Path(__file__).resolve().parent.name # To be able to use relative imports when run directly - never override a __package__ Python already set (see README)

from enum import auto, IntEnum
import logging as _logging
import socket as _socket

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

def getSSH(
	username: str,
	hostnames: str | list[str],
	password: str = None,
	hosts: str | list[str] = None,
	keyFilename: str = None,
	timeout: float = 5,
	port = 22,
	silent = False
) -> tuple[_paramiko.SSHClient, bool]:
	# paramiko reports a failed connection twice: as the exception handled below, and through
	# the "paramiko" logger, from its transport thread, as "Exception (client): ..." plus a
	# full traceback. In a program that never configured logging, that second copy lands on
	# stderr via logging's last-resort handler - a wall of traceback in front of our own
	# one-line message, e.g. whenever 127.0.0.1 is an adb forward with no server behind it.
	# A NullHandler stops only that fallback: a program that does configure logging (like
	# ssh-server.py) still gets every paramiko record through propagation.
	paramiko_logger = _logging.getLogger("paramiko")
	if not any(isinstance(handler, _logging.NullHandler) for handler in paramiko_logger.handlers):
		paramiko_logger.addHandler(_logging.NullHandler())

	ssh = _paramiko.SSHClient()
	ssh.set_missing_host_key_policy(_paramiko.AutoAddPolicy())

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

	there_was_SSH_error = False
	for username, hostname, port in hosts:
		errorMessage = None
		try:
			if not silent:
				print(f"Attempting to connect to {_clr(username, 'green')}@{_clr(hostname, 'green')}:{_clr(port, 'green')} ...")
			ssh.connect(
				hostname     = hostname   ,
				username     = username   ,
				password     = password   ,
				key_filename = keyFilename,
				timeout      = timeout    ,
				port         = port       ,
			)
			break
		except _BadHostKeyException:
			errorMessage = f"ERROR: The server's host key could not be verified for {hostname}"
		except _AuthenticationException:
			errorMessage = f"ERROR: Authentication failed when connecting to {hostname}"
		except _PartialAuthentication:
			errorMessage = f"ERROR: Partial authentication occurred when connecting to {hostname}"
		except _NoValidConnectionsError:
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
			errorMessage = f"ERROR: Socket error while connecting to {hostname}: {e}"

		if errorMessage:
			there_was_SSH_error = True
			_cprint(errorMessage, _COLOR_ERROR)

	if errorMessage:
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
