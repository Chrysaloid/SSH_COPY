from termcolor import colored as clr
import os
import json
import posixpath
import argparse

from SimpleError import SimpleError
from getSSH import getSSH
from getPlatform import WINDOWS

if WINDOWS:
	os.system("color")

parser = argparse.ArgumentParser(description="Parse connection details")

parser.add_argument("-u", "--username"               , required=True, help="Remote username")
parser.add_argument("-H", "--hostname"               , required=True, help="Remote host address")
parser.add_argument("-p", "--password"               , required=True, help="Remote password")
parser.add_argument("-r", "--local-folder"           , required=True, help="Remote folder absolute path", dest="localFolder")
parser.add_argument("-r", "--remote-get-files-script", required=True, help="Remote folder absolute path", dest="remoteGetFilesScript")

parser.add_argument("-P", "--port"          , default=22, type=int , help="Remote port (default: 22)")
parser.add_argument("-T", "--timeout"       , default=1, type=float, help="TCP 3-way handshake timeout in seconds (default: 1)")
parser.add_argument("-t", "--preserve-times", action="store_true"  , help="If set, modification times will be preserved", dest="preserveTimes")
parser.add_argument("-d", "--dont-close"    , action="store_true"  , help="Don't auto-close console window at the end if no error occured. You will have to close it manually or by pressing ENTER", dest="dontClose")

args = parser.parse_args()

username             : str   = args.username
hostname             : str   = args.hostname
password             : str   = args.password
localFolder          : str   = args.localFolder
remoteGetFilesScript : str   = args.remoteGetFilesScript
port                 : int   = args.port
timeout              : float = args.timeout
preserveTimes        : bool  = args.preserveTimes
dontClose            : bool  = args.dontClose

if not os.path.isdir(localFolder):
	raise SimpleError(f'Folder "{localFolder}" does not exist')
else:
	localFolder = localFolder.replace("\\", "/")

ssh = getSSH(username, hostname, password, timeout, port)

stdIn, stdOut, stdErr = ssh.exec_command(f'python "{remoteGetFilesScript}"')

exitStatus = stdOut.channel.recv_exit_status() # Wait for command to finish

if exitStatus != 0: # Command failed
	if exitStatus == 69: # (¬‿¬)
		print(stdOut.read().decode("utf-8").strip())
		raise SimpleError("No files/folders selected")
	errorOutput = stdErr.read().decode("utf-8").strip()
	raise RuntimeError(f"Remote command failed with exit code {exitStatus}:\n{errorOutput}")

rawOutput = stdOut.read().decode("utf-8")
try:
	obj = json.loads(rawOutput)
except json.JSONDecodeError as e:
	ssh.close()
	raise RuntimeError(f"Failed to parse JSON from remote script: {e}\nOutput:\n{rawOutput}")

sftp = ssh.open_sftp()

baseFolder: str       = obj["baseFolder"]
subFolders: list[str] = obj["subFolders"]
files:      list[str] = obj["files"]

for subFolder in subFolders:
	fullPath = posixpath.join(localFolder, subFolder)
	os.mkdir(fullPath)

print("Getting files:\n")
for file in files:
	remotePath = posixpath.join(baseFolder , file)
	localPath  = posixpath.join(localFolder, file)
	sftp.get(remotePath, localPath)
	if preserveTimes:
		info = sftp.stat(remotePath)
		sftp.utime(localPath, (info.st_atime, info.st_mtime))
	print(file)
print(f"\nSuccessfully got {clr(len(files), "green")} file(s)\n")

sftp.close()
ssh.close()

if dontClose:
	input("\nPress ENTER to continue...")
