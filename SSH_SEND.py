import ctypes
from termcolor import colored as clr
import os
import paramiko
import stat
from time import sleep
import argparse

from SimpleError import SimpleError
from getSSH import getSSH
from getPlatform import WINDOWS

TITLE = "SSH COPY"
SSH_TIMEOUT = 0.5 # s, TCP 3-way handshake timeout
EXPECTED_NUM_ARGS = 1 + 4

if WINDOWS:
	from getSelectedFilesFromExplorer import getSelectedFilesFromExplorer
	ctypes.windll.kernel32.SetConsoleTitleW(TITLE) # Hide title from shortcut
	os.system("color")
else:
	from getSelectedFilesFromStdIn import getSelectedFilesFromStdIn
	print(f"\33]0;{TITLE}\a", end="", flush=True) # Hide title

parser = argparse.ArgumentParser(description="Parse connection details")

parser.add_argument("-u", "--username"     , required=True, help="Remote username")
parser.add_argument("-H", "--hostname"     , required=True, help="Remote host address")
parser.add_argument("-p", "--password"     , required=True, help="Remote password")
parser.add_argument("-r", "--remote-folder", required=True, help="Remote folder absolute path", dest="remoteFolder")

parser.add_argument("-P", "--port"          , default=22, type=int, help="Remote port (default: 22)")
parser.add_argument("-t", "--preserve-times", action="store_true" , help="If set, modification times will be preserved", dest="preserveTimes")
parser.add_argument("-0", "--zero-file"     , action="store_true" , help="Create a file named 0 at the end of transfer. Useful for file-watching scripts on the remote machine", dest="zeroFile")

args = parser.parse_args()

username      : str  = args.username
hostname      : str  = args.hostname
password      : str  = args.password
remoteFolder  : str  = args.remoteFolder
port          : int  = args.port
preserveTimes : bool = args.preserveTimes
zeroFile      : bool = args.zeroFile

selectedFiles = getSelectedFilesFromExplorer() if WINDOWS else getSelectedFilesFromStdIn()

# Main upload process
ssh = getSSH(username, hostname, password, SSH_TIMEOUT, port=port)

sftp = ssh.open_sftp()

def remoteFolderExists(sftp: paramiko.SFTPClient, remotePath: str) -> bool:
	try:
		info = sftp.stat(remotePath) # Raises FileNotFoundError if it doesn't exist
		return stat.S_ISDIR(info.st_mode) # True if it's a directory
	except FileNotFoundError:
		return False

if not remoteFolderExists(sftp, remoteFolder):
	raise SimpleError(f'The remote folder "{remoteFolder}" does not exist')

totalFiles = 0
baseFolder = os.path.dirname(selectedFiles[0])
def sftpUpload(sftp: paramiko.SFTPClient, localPath: str, remotePath: str):
	"""Upload file or folder recursively, printing relative paths."""
	global totalFiles
	statInfo = os.stat(localPath)
	if stat.S_ISREG(statInfo.st_mode): # is file?
		print(os.path.relpath(localPath, baseFolder))
		sftp.put(localPath, remotePath)
		if preserveTimes:
			sftp.utime(remotePath, (statInfo.st_atime, statInfo.st_mtime))
		totalFiles += 1
	elif stat.S_ISDIR(statInfo.st_mode): # is directory?
		try:
			sftp.mkdir(remotePath)
		except IOError:
			pass # Directory may already exist
		for item in os.listdir(localPath):
			sftpUpload(sftp, os.path.join(localPath, item), os.path.join(remotePath, item).replace("\\", "/"))

print("Sending files:\n")
for path in selectedFiles:
	baseName = os.path.basename(path)
	remoteTarget = os.path.join(remoteFolder, baseName).replace("\\", "/")
	sftpUpload(sftp, path, remoteTarget)

if zeroFile:
	with sftp.open(os.path.join(remoteFolder, "0").replace("\\", "/"), "w"):
		pass

print(f"\nSuccessfully sent {clr(totalFiles, "green")} file(s)\n")

sftp.close()
ssh.close()

# sleep(1)
# input("Press ENTER to continue...")
