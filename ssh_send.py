import sys; from pathlib import Path; p = Path(__file__).resolve().parent; __package__ = p.name; sys.path.append(p.parent.as_posix()) # To be able to use relative imports

import argparse
import os
import posixpath
import time

import paramiko
from termcolor import colored as clr

start = time.time()

from .argparse_utils import ArgumentParser_colored_error, COMMON_FORMATTER_CLASS
from .common_constants import COLOR_ERROR, COLOR_ERROR_BACK, COLOR_OK, COLOR_WARN
from .file_utils import is_dir, is_file, Local_DirEntry
from .my_system import WINDOWS
from .simple_error import Simple_error
from .ssh_utils import assert_remote_folder_exists, get_ssh, remote_mkdir

TITLE = "SSH SEND"

parser = ArgumentParser_colored_error(
	description="Copies selected files (and folders recursively) in Windows Explorer or Nautilus to a folder on a remote machine.",
	formatter_class=COMMON_FORMATTER_CLASS,
)

required = parser.add_argument_group("Required arguments")
parser._action_groups = [required, parser._optionals]

required.add_argument("-u", "--username"     , required=True, help="Remote username")
required.add_argument("-H", "--hostname"     , required=True, nargs="+", help="Remote host's address. You can specify multiple if host can appear under multiple adresses")
required.add_argument("-p", "--password"     , required=True, help="Remote password")
required.add_argument("-r", "--remote-folder", required=True, help="Remote folder's absolute path", dest="remote_folder")

parser._optionals.title = "Optional arguments"

parser.add_argument("-P", "--port"          , default=22, type=int, help="Remote port (default: 22)")
parser.add_argument("-T", "--timeout"       , default=5.0, type=float, help="TCP 3-way handshake timeout in seconds (default: 5.0)", metavar="SECONDS")
parser.add_argument("-t", "--preserve-times", action="store_true" , help="If set, modification times will be preserved", dest="preserve_times")
parser.add_argument("-0", "--zero-file"     , action="store_true" , help="Create a file named 0 at the end of transfer. Useful for file-watching scripts on the remote machine", dest="zero_file")
parser.add_argument("-c", "--end-command"   , help="Command to run on the remote machine after file transfer", dest="end_command")
parser.add_argument("-d", "--dont-close"    , action="store_true" , help="Don't auto-close console window at the end if no error occurred. You will have to close it manually or by pressing ENTER", dest="dont_close")
parser.add_argument("-i", "--hide-title"    , action="store_true" , help=f"Hide window title and replace it with {TITLE}", dest="hide_title")
# parser.add_argument("-n", "--handle-non-abs-paths", action="store_true" , help=f"If a file path does not start with --prefix try to recursively search for it in --search-root folder", dest="handleNonAbsPaths")

args = parser.parse_args()

username       : str   = args.username
hostname       : str   = args.hostname
password       : str   = args.password
remote_folder  : str   = args.remote_folder
port           : int   = args.port
timeout        : float = args.timeout
preserve_times : bool  = args.preserve_times
zero_file      : bool  = args.zero_file
end_command    : str   = args.end_command
dont_close     : bool  = args.dont_close
hide_title     : bool  = args.hide_title
# handleNonAbsPaths : bool  = args.handleNonAbsPaths

if WINDOWS:
	import ctypes

	from get_selected_files_from_explorer import get_selected_files_from_explorer
	if hide_title:
		ctypes.windll.kernel32.SetConsoleTitleW(TITLE) # Hide title from shortcut
	os.system("color")
else:
	from get_selected_files_from_stdin import get_selected_files_from_stdin
	if hide_title:
		print(f"\33]0;{TITLE}\a", end="", flush=True) # Hide title

selected_files = get_selected_files_from_explorer() if WINDOWS else get_selected_files_from_stdin()

# Main upload process
ssh, there_was_ssh_error = get_ssh(
	username  = username,
	hostnames = hostname,
	password  = password,
	timeout   = timeout ,
	port      = port    ,
)
sftp = ssh.open_sftp()

remote_folder = remote_folder.replace("\\", "/")
assert_remote_folder_exists(sftp, remote_folder)

total_files = 0
base_folder = posixpath.dirname(selected_files[0])
def sftp_upload(sftp: paramiko.SFTPClient, local_entry: os.DirEntry, remote_path: str):
	"""Upload file or folder recursively, printing relative paths."""
	global total_files
	info = local_entry.stat(follow_symlinks=False)
	if is_file(info):
		print(posixpath.relpath(local_entry.path, base_folder))
		sftp.put(local_entry.path, remote_path)
		if preserve_times:
			sftp.utime(remote_path, (info.st_atime, info.st_mtime))
		total_files += 1
	elif is_dir(info):
		remote_mkdir(sftp, remote_path)
		with os.scandir(local_entry.path) as dir:
			for entry in dir:
				sftp_upload(sftp, entry, posixpath.join(remote_path, entry.name))

print("Sending files:\n")
for path in selected_files:
	if not os.path.exists(path):
		print(f"{clr("Warning!", COLOR_WARN)} Non existent path: {path}")
		continue
	entry = Local_DirEntry(path)
	remote_target = posixpath.join(remote_folder, entry.name)
	sftp_upload(sftp, entry, remote_target)

if zero_file:
	print("Sending 0 file")
	with sftp.open(posixpath.join(remote_folder, "0")):
		pass

sftp.close()
print(f"\nSuccessfully sent {clr(total_files + int(zero_file), COLOR_OK)} file(s)\n")

exit_status = 0
if end_command:
	end_command = end_command.strip()
	if end_command:
		print(f"Executing remote command '{end_command}'...\n")

		channel = ssh.get_transport().open_session()
		channel.exec_command(end_command)
		channel.set_combine_stderr(True) # Combine stdout + stderr into one stream
		with channel.makefile("r") as stream: # Wrap the channel in a file-like object and iterate
			for line in stream:
				print(line, end="") # line already has \n

		exit_status = channel.recv_exit_status()
		if exit_status:
			print(f"{clr("Exit status:", COLOR_ERROR)} {clr(exit_status, COLOR_ERROR_BACK)}")

ssh.close()

print(f"Execution time: {time.time() - start:.3f} s")

if exit_status:
	exit(exit_status)

if dont_close or there_was_ssh_error:
	input(clr("\nPress ENTER to continue...", COLOR_OK))
