from termcolor import colored as clr
import os
import paramiko
import argparse
import time

start = time.time()

from SimpleError import SimpleError
from sshUtils import getSSH
from getPlatform import WINDOWS
from fileUtils import isFile, isDir, assertRemoteFolderExists

TITLE = "SSH SEND"

if WINDOWS:
	import ctypes
	from getSelectedFilesFromExplorer import getSelectedFilesFromExplorer
	ctypes.windll.kernel32.SetConsoleTitleW(TITLE) # Hide title from shortcut
	os.system("color")
else:
	from getSelectedFilesFromStdIn import getSelectedFilesFromStdIn
	print(f"\33]0;{TITLE}\a", end="", flush=True) # Hide title

parser = argparse.ArgumentParser(description="Parse connection details")

parser.add_argument("-u", "--username"     , required=True, help="Remote username")
parser.add_argument("-H", "--hostname"     , required=True, help="Remote host's address")
parser.add_argument("-p", "--password"     , required=True, help="Remote password")
parser.add_argument("-r", "--remote-folder", required=True, help="Remote folder's absolute path", dest="remoteFolder")

parser.add_argument("-P", "--port"          , default=22, type=int, help="Remote port (default: 22)")
parser.add_argument("-T", "--timeout"       , default=1, type=float, help="TCP 3-way handshake timeout in seconds (default: 1)")
parser.add_argument("-t", "--preserve-times", action="store_true" , help="If set, modification times will be preserved", dest="preserveTimes")
parser.add_argument("-0", "--zero-file"     , action="store_true" , help="Create a file named 0 at the end of transfer. Useful for file-watching scripts on the remote machine", dest="zeroFile")
parser.add_argument("-c", "--end-command"   , help="Command to run on the remote machine after file transfer", dest="endCommand")
parser.add_argument("-d", "--dont-close"    , action="store_true" , help="Don't auto-close console window at the end if no error occurred. You will have to close it manually or by pressing ENTER", dest="dontClose")

args = parser.parse_args()

username      : str   = args.username
hostname      : str   = args.hostname
password      : str   = args.password
remoteFolder  : str   = args.remoteFolder
port          : int   = args.port
timeout       : float = args.timeout
preserveTimes : bool  = args.preserveTimes
zeroFile      : bool  = args.zeroFile
endCommand    : str   = args.endCommand
dontClose     : bool  = args.dontClose

selectedFiles = getSelectedFilesFromExplorer() if WINDOWS else getSelectedFilesFromStdIn()

# Main upload process
ssh = getSSH(username, hostname, password, timeout, port)
sftp = ssh.open_sftp()

assertRemoteFolderExists(sftp, remoteFolder)

totalFiles = 0
baseFolder = os.path.dirname(selectedFiles[0])
def sftpUpload(sftp: paramiko.SFTPClient, localPath: str, remotePath: str):
	"""Upload file or folder recursively, printing relative paths."""
	global totalFiles
	fileInfo = os.stat(localPath)
	if isFile(fileInfo):
		print(os.path.relpath(localPath, baseFolder))
		sftp.put(localPath, remotePath)
		if preserveTimes:
			sftp.utime(remotePath, (fileInfo.st_atime, fileInfo.st_mtime))
		totalFiles += 1
	elif isDir(fileInfo):
		try:
			sftp.mkdir(remotePath)
		except IOError: pass # Directory may already exist
		for item in os.listdir(localPath):
			sftpUpload(sftp, os.path.join(localPath, item), os.path.join(remotePath, item).replace("\\", "/"))

print("Sending files:\n")
for path in selectedFiles:
	baseName = os.path.basename(path)
	remoteTarget = os.path.join(remoteFolder, baseName).replace("\\", "/")
	sftpUpload(sftp, path, remoteTarget)

if zeroFile:
	print("Sending 0 file")
	with sftp.open(os.path.join(remoteFolder, "0").replace("\\", "/"), "w"):
		pass

sftp.close()
print(f"\nSuccessfully sent {clr(totalFiles + int(zeroFile), "green")} file(s)\n")

exitStatus = 0
if endCommand:
	endCommand = endCommand.strip()
	if endCommand:
		print(f"Executing remote command '{endCommand}'...\n")

		channel = ssh.get_transport().open_session()
		channel.exec_command(endCommand)
		channel.set_combine_stderr(True) # Combine stdout + stderr into one stream
		with channel.makefile("r") as stream: # Wrap the channel in a file-like object and iterate
			for line in stream:
				print(line, end="") # line already has \n

		exitStatus = channel.recv_exit_status()
		if exitStatus:
			print(f"{clr("Exit status:", "red")} {clr(exitStatus, "on_red")}")

ssh.close()

print(f"\nExecution time: {time.time() - start:.3f} s")

if exitStatus:
	exit(exitStatus)

if dontClose:
	input(clr("\nPress ENTER to continue...", "green"))
