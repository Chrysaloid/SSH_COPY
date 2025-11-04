from termcolor import colored as clr
import socket
import paramiko
from paramiko.ssh_exception import (
	BadHostKeyException,
	AuthenticationException,
	SSHException,
	NoValidConnectionsError,
	PartialAuthentication,
)
from SimpleError import SimpleError
from fileUtils import isDir, iteratePathParts
from LocalSFTPAttributes import LocalSFTPAttributes

def getSSH(username: str, hostname: str, password: str, keyFilename: str = None, TIMEOUT: float = 5, port = 22, silent = False):
	ssh = paramiko.SSHClient()
	ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

	errorMessage = None
	try:
		if not silent:
			print(f"Attempting to connect to {clr(username, 'green')}@{clr(hostname, 'green')} ...")
		ssh.connect(hostname, username=username, password=password, key_filename=keyFilename, timeout=TIMEOUT, port=port)
	except BadHostKeyException:
		errorMessage = f"ERROR: The server's host key could not be verified for {hostname}"
	except AuthenticationException:
		errorMessage = f"ERROR: Authentication failed when connecting to {hostname}"
	except PartialAuthentication:
		errorMessage = f"ERROR: Partial authentication occurred when connecting to {hostname}"
	except socket.error as e:
		errorMessage = f"ERROR: Socket error while connecting to {hostname}: {e}"
	except NoValidConnectionsError:
		errorMessage = f"ERROR: No valid connections could be made to {hostname} (connection refused or unreachable)"
	except SSHException:
		errorMessage = f"ERROR: General SSH error occurred while connecting to {hostname} (probably timeout after {TIMEOUT} seconds)"

	if errorMessage:
		raise SimpleError(errorMessage)

	return ssh

def remoteIsWindows(ssh: paramiko.SSHClient) -> bool:
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

	raise SimpleError(f"Could not determine if remote is Windows due to errors") # Should not happen?

def isFolderCaseSensitive(ssh: paramiko.SSHClient, pathToFolder: str) -> bool:
	stdin, stdout, stderr = ssh.exec_command(f'C:/Windows/System32/fsutil.exe file queryCaseSensitiveInfo "{pathToFolder}" 2>&1')
	output = stdout.read().decode(errors="ignore")
	outputProcessed = output.strip().lower()

	if outputProcessed.endswith("enabled."):
		return True
	if outputProcessed.endswith("disabled."):
		return False

	raise RuntimeError(f"Unexpected fsutil output:\n{output}")

def remoteFolderExists(sftp: paramiko.SFTPClient, remotePath: str) -> bool:
	try:
		fileInfo = sftp.stat(remotePath) # Raises FileNotFoundError if it doesn't exist
		return isDir(fileInfo)
	except FileNotFoundError:
		return False

def assertRemoteFolderExists(sftp: paramiko.SFTPClient, remotePath: str, additionalComment = ""):
	if not remoteFolderExists(sftp, remotePath):
		raise SimpleError(f'The remote folder "{remotePath}" does not exist or is not a folder{additionalComment}')

def remoteMkdir(sftp: paramiko.SFTPClient, remotePath: str):
	""" Returns True if folder was created and False if it already exists """
	try:
		sftp.mkdir(remotePath)
		return True
	except IOError:
		return False

def ensureRemoteFolderExists(sftp: paramiko.SFTPClient, remotePath: str):
	if not remoteFolderExists(sftp, remotePath):
		for part in iteratePathParts(remotePath):
			remoteMkdir(sftp, part)

class RemoteListDir:
	def __init__(self, ssh: paramiko.SSHClient, pythonStr = "python", init = False):
		self.ssh = ssh
		self.pythonStr = pythonStr
		self.stdin: paramiko.ChannelFile | None = None
		self.stdout: paramiko.ChannelFile | None = None
		self.stderr: paramiko.ChannelFile | None = None
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
			self.stdin = None # reset stdin so the remote script gets recreated on the next use # TODO find a better solution to this
			raise SimpleError(
				f'RemoteListDir.listdir_attr: remote script returned error when listing folder "{path}":\n{ \
				self.stderr.read().decode(errors="ignore").strip() \
				or self.stdout.read().decode(errors="ignore").strip()}'
			)

		entries = []
		while (line := self.stdout.readline().rstrip()):
			filename, st_mode, st_size, st_atime, st_mtime = line.split("/")
			entries.append(LocalSFTPAttributes.from_values(
				filename=filename,
				st_mode =int(st_mode , 16),
				st_size =int(st_size , 16),
				st_atime=int(st_atime, 16),
				st_mtime=int(st_mtime, 16),
			))
		return entries

def remoteHasPython(ssh: paramiko.SSHClient, throwOnNotFound = True, enforcePythonVer = "3") -> str:
	"""
	Returns python alias that worked.
	You can pass empty str as enforcePythonVer to not enforce version.
	"""
	for candidate in ("python", "python3", "py"):
		stdin, stdout, stderr = ssh.exec_command(f"{candidate} --version")
		if stdout.read().decode(errors="ignore").strip().lower().startswith(f"python {enforcePythonVer}"):
			return candidate

	if throwOnNotFound:
		raise SimpleError(f"No Python found remotely")
	else:
		return ""
