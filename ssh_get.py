import sys; from pathlib import Path; p = Path(__file__).resolve().parent; __package__ = p.name; sys.path.append(p.parent.as_posix()) # To be able to use relative imports

import argparse
import json
import os
import posixpath

from termcolor import colored as clr

from .argparse_utils import ArgumentParser_colored_error, COMMON_FORMATTER_CLASS
from .common_constants import COLOR_OK
from .my_system import WINDOWS
from .simple_error import Simple_error
from .ssh_utils import get_ssh

TITLE = "SSH GET"

if WINDOWS:
	import ctypes
	ctypes.windll.kernel32.SetConsoleTitleW(TITLE) # Hide title from shortcut
	os.system("color")
else:
	print(f"\33]0;{TITLE}\a", end="", flush=True) # Hide title

parser = ArgumentParser_colored_error(
	description="Copies selected files (and folders recursively) in Windows Explorer or Nautilus from a folder on a remote machine.",
	formatter_class=COMMON_FORMATTER_CLASS,
)

parser.add_argument("-u", "--username"               , required=True, help="Remote username")
parser.add_argument("-H", "--hostname"               , required=True, help="Remote host's address")
parser.add_argument("-p", "--password"               , required=True, help="Remote password")
parser.add_argument("-l", "--local-folder"           , required=True, help="Local folder's absolute path", dest="local_folder")
parser.add_argument("-r", "--remote-get-files-script", required=True, help="Remote get_selected_files_from_explorer_recurse_stdout.py absolute path", dest="remote_get_files_script")

parser.add_argument("-P", "--port"          , default=22, type=int , help="Remote port (default: 22)")
parser.add_argument("-T", "--timeout"       , default=5, type=float, help="TCP 3-way handshake timeout in seconds (default: 5.0)")
parser.add_argument("-t", "--preserve-times", action="store_true"  , help="If set, modification times will be preserved", dest="preserve_times")
parser.add_argument("-d", "--dont-close"    , action="store_true"  , help="Don't auto-close console window at the end if no error occurred. You will have to close it manually or by pressing ENTER", dest="dont_close")

args = parser.parse_args()

username                : str   = args.username
hostname                : str   = args.hostname
password                : str   = args.password
local_folder            : str   = args.local_folder
remote_get_files_script : str   = args.remote_get_files_script
port                    : int   = args.port
timeout                 : float = args.timeout
preserve_times          : bool  = args.preserve_times
dont_close              : bool  = args.dont_close

if not os.path.isdir(local_folder):
	raise Simple_error(f'Folder "{local_folder}" does not exist')
else:
	local_folder = local_folder.replace("\\", "/")

ssh, there_was_ssh_error = get_ssh(username, hostname, password, timeout, port)

std_in, std_out, std_err = ssh.exec_command(f'python "{remote_get_files_script}"')

exit_status = std_out.channel.recv_exit_status() # Wait for command to finish

if exit_status != 0: # Command failed
	if exit_status == 69: # (¬‿¬)
		print(std_out.read().decode("utf-8").strip())
		raise Simple_error("No files/folders selected")
	error_output = std_err.read().decode("utf-8").strip()
	raise RuntimeError(f"Remote command failed with exit code {exit_status}:\n{error_output}")

raw_output = std_out.read().decode("utf-8")
try:
	obj = json.loads(raw_output)
except json.JSONDecodeError as e:
	ssh.close()
	raise RuntimeError(f"Failed to parse JSON from remote script: {e}\nOutput:\n{raw_output}")

sftp = ssh.open_sftp()

base_folder: str       = obj["baseFolder"]
sub_folders: list[str] = obj["subFolders"]
files:       list[str] = obj["files"]

for sub_folder in sub_folders:
	full_path = posixpath.join(local_folder, sub_folder)
	os.mkdir(full_path)

print("Getting files:\n")
for file in files:
	remote_path = posixpath.join(base_folder , file)
	local_path  = posixpath.join(local_folder, file)
	sftp.get(remote_path, local_path)
	if preserve_times:
		info = sftp.stat(remote_path)
		os.utime(local_path, (info.st_atime, info.st_mtime))
	print(file)
print(f"\nSuccessfully got {clr(len(files), COLOR_OK)} file(s)\n")

sftp.close()
ssh.close()

if dont_close or there_was_ssh_error:
	input(clr("\nPress ENTER to continue...", COLOR_OK))
