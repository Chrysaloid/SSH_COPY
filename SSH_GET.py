from termcolor import colored as clr
import os
import sys
import paramiko
import json
import posixpath

from SimpleError import SimpleError
from getArguments import getArguments
from getSSH import getSSH

SSH_TIMEOUT = 0.5 # s, TCP 3-way handshake timeout
EXPECTED_NUM_ARGS = 1 + 5
WINDOWS = sys.platform == "win32"

if WINDOWS:
	os.system("color")

username, hostname, password, localFolder, remoteGetFilesScript = getArguments(EXPECTED_NUM_ARGS)

if not os.path.isdir(localFolder):
	raise SimpleError(f'Folder "{localFolder}" does not exist')
else:
	localFolder = localFolder.replace("\\", "/")

ssh = getSSH(username, hostname, password, SSH_TIMEOUT)

stdin, stdout, stderr = ssh.exec_command(f'python "{remoteGetFilesScript}"')

exit_status = stdout.channel.recv_exit_status() # Wait for command to finish

if exit_status != 0: # Command failed
	if exit_status == 69: # (¬‿¬)
		print(stdout.read().decode("utf-8").strip())
		raise SimpleError("No files/folders selected")
	error_output = stderr.read().decode("utf-8").strip()
	raise RuntimeError(f"Remote command failed with exit code {exit_status}:\n{error_output}")

raw_output = stdout.read().decode("utf-8")
try:
	obj = json.loads(raw_output)
except json.JSONDecodeError as e:
	ssh.close()
	raise RuntimeError(f"Failed to parse JSON from remote script: {e}\nOutput:\n{raw_output}")

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
	print(file)
print(f"\nSuccessfully got {clr(len(files), "green")} file(s)\n")

sftp.close()
ssh.close()

# input("Press ENTER to continue...")
