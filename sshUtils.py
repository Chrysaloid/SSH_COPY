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
from fileUtils import isDir

def getSSH(username: str, hostname: str, password: str, TIMEOUT: float = 1, port = 22, silent = False):
	ssh = paramiko.SSHClient()
	ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

	errorMessage = None
	try:
		if not silent:
			print(f"Attempting to connect to {clr(username, 'green')}@{clr(hostname, 'green')} ...")
		ssh.connect(hostname, username=username, password=password, timeout=TIMEOUT, port=port)
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

def assertRemoteFolderExists(sftp: paramiko.SFTPClient, remotePath: str):
	if not remoteFolderExists(sftp, remotePath):
		raise SimpleError(f'The remote folder "{remotePath}" does not exist or is not a folder')
