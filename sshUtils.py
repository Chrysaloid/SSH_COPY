from pathlib import Path as _Path; __package__ = _Path(__file__).resolve().parent.name # To be able to use relative imports

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
from .fileUtils import isDir as _isDir, iteratePathParts as _iteratePathParts
from .LocalSFTPAttributes import LocalSFTPAttributes as _LocalSFTPAttributes
from .SimpleError import SimpleError as _SimpleError

def getSSH(
	username: str,
	hostnames: str | list[str],
	password: str,
	keyFilename: str = None,
	timeout: float = 5,
	port = 22,
	silent = False
) -> tuple[_paramiko.SSHClient, bool]:
	ssh = _paramiko.SSHClient()
	ssh.set_missing_host_key_policy(_paramiko.AutoAddPolicy())

	if isinstance(hostnames, str): hostnames = [hostnames]

	thereWasSSHError = False
	for hostname in hostnames:
		errorMessage = None
		try:
			if not silent:
				print(f"Attempting to connect to {_clr(username, 'green')}@{_clr(hostname, 'green')} ...")
			ssh.connect(
				hostname     = hostname   ,
				username     = username   ,
				password     = password   ,
				key_filename = keyFilename,
				timeout      = timeout    ,
				port         = port
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
			thereWasSSHError = True
			_cprint(errorMessage, _COLOR_ERROR)

	if errorMessage:
		raise _SimpleError("", None)

	return ssh, thereWasSSHError

def remoteIsWindows(ssh: _paramiko.SSHClient) -> bool:
	try:
		banner = ssh.get_transport().remote_version.lower()
		if "windows" in banner:
			return True
	except Exception:
		pass

	try:
		stdin, stdout, stderr = ssh.exec_command("uname -s")
		out = stdout.read().decode(errors="ignore").strip().lower()
		if out:
			if out.startswith(("linux", "darwin", "freebsd", "netbsd", "openbsd")):
				return False
			if out.startswith(("msys_nt", "cygwin_nt", "mingw")):
				return True
			# Unexpected uname string -> treat as non-Windows
			return False
	except Exception:
		pass

	# Fallback: try cmd.exe (may also work in WSL, so only used if uname absent)
	try:
		stdin, stdout, stderr = ssh.exec_command("cmd.exe /c echo %OS%")
		out = stdout.read().decode(errors="ignore").strip().lower()
		if out.startswith("windows"):
			return True
	except Exception:
		pass

	raise _SimpleError(f"Could not determine if remote is Windows due to errors") # Should not happen?

def isFolderCaseSensitive(ssh: _paramiko.SSHClient, pathToFolder: str) -> bool:
	stdin, stdout, stderr = ssh.exec_command(f'C:/Windows/System32/fsutil.exe file queryCaseSensitiveInfo "{pathToFolder}" 2>&1')
	output = stdout.read().decode(errors="ignore")
	outputProcessed = output.strip().lower()

	if outputProcessed.endswith("enabled."):
		return True
	if outputProcessed.endswith("disabled."):
		return False

	raise RuntimeError(f"Unexpected fsutil output:\n{output}")

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
	if not remoteFolderExists(sftp, remotePath):
		for part in _iteratePathParts(remotePath):
			remoteMkdir(sftp, part)

class RemoteListDir:
	def __init__(self, ssh: _paramiko.SSHClient, pythonStr = "python", init = False):
		self.ssh = ssh
		self.pythonStr = pythonStr
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
				"			i = e.stat(follow_symlinks=0); print(e.name, '%x/%x/%x/%x' % (i.st_mode, i.st_size, int(i.st_atime), int(i.st_mtime)), sep='/')\\n"
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
