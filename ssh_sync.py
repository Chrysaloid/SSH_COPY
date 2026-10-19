# region #* IMPORTS
import sys; from pathlib import Path; p = Path(__file__).resolve().parent; __package__ = p.name; sys.path.append(p.parent.as_posix()) # To be able to use relative imports

import argparse
from collections import defaultdict
from datetime import datetime
from enum import auto, IntEnum
from fnmatch import fnmatch, fnmatchcase
from itertools import chain
import os
import posixpath
import shutil
import sys
from time import perf_counter
from typing import Callable, List, Tuple

import paramiko
from termcolor import colored as clr, cprint

start = perf_counter()

from .argparse_utils import ArgumentParser_colored_error, COMMON_FORMATTER_CLASS, Include_exclude_Action, Name_filter, No_repeat_Action
from .common_constants import COLOR_EMPHASIS, COLOR_ERROR, COLOR_OK, COLOR_WARN
from .file_utils import assert_folder_exists, ensure_folder_exists, is_dir, is_file, mkdir as local_mkdir, modified_date
from .is_folder_case_sensitive import is_folder_case_sensitive as is_local_folder_case_sensitive
from .local_sftp_attributes import local_listdir_attr
from .my_system import WINDOWS
from .print_rel_time import get_rel_time
from .simple_error import Simple_error
from .ssh_utils import (
	assert_remote_folder_exists,
	detect_remote_os,
	ensure_remote_folder_exists,
	get_ssh,
	is_folder_case_sensitive as is_remote_folder_case_sensitive,
	Os,
	remote_has_python,
	Remote_list_dir,
	remote_mkdir as remote_mkdir_base
)

# endregion

TITLE = "SSH SYNC"
SOURCE_STR = "source"
DEST_STR   = "destination"

if WINDOWS:
	import ctypes
	ctypes.windll.kernel32.SetConsoleTitleW(TITLE) # Hide title from shortcut
	os.system("color")
else:
	print(f"\33]0;{TITLE}\a", end="", flush=True) # Hide title

# region #* PARAMETER PARSING
parser = ArgumentParser_colored_error( # Remaining letter argument names: O W h m q
	description="Copy or sync files between folders on remote or local machines",
	formatter_class=COMMON_FORMATTER_CLASS,
)

required = parser.add_argument_group("Required arguments")
parser._action_groups = [required, parser._optionals]

required.add_argument("-l", "--local-folder" , required=True, action=No_repeat_Action, help="Local folder's absolute path"            , dest="local_folder" , metavar="ABSOLUTE_PATH")
required.add_argument("-r", "--remote-folder", required=True, action=No_repeat_Action, help="Remote (or local) folder's absolute path", dest="remote_folder", metavar="ABSOLUTE_PATH")

class Mode(IntEnum):
	SYNC = auto()
	COPY = auto()

MODE_DICT = {mode.name.lower(): mode for mode in Mode}

def get_mode(mode_str: str):
	mode_str = mode_str.lower()
	try:
		return MODE_DICT[mode_str].value
	except:
		raise Simple_error(f'-m/--mode option should be one of the values: {",".join(MODE_DICT.keys())}')

class Action(IntEnum):
	NONE = auto()
	CONTINUE = auto()
	RETURN = auto()

parser._optionals.title = "Optional common arguments"

parser.add_argument("-i", "--include-files"            , default=[], action=Include_exclude_Action, nargs="*", help="Glob patterns for files to include in copy/sync"                   , dest="in_exclude_files"  , metavar=("PATTERN_1", "PATTERN_2"))
parser.add_argument("-e", "--exclude-files"            , default=[], action=Include_exclude_Action, nargs="*", help="Glob patterns for files to exclude in copy/sync"                   , dest="in_exclude_files"  , metavar=("PATTERN_1", "PATTERN_2"))
parser.add_argument("-c", "--include-files-case"       , default=[], action=Include_exclude_Action, nargs="*", help="Glob patterns for files to include in copy/sync (case-sensitive)"  , dest="in_exclude_files"  , metavar=("PATTERN_1", "PATTERN_2"))
parser.add_argument("-a", "--exclude-files-case"       , default=[], action=Include_exclude_Action, nargs="*", help="Glob patterns for files to exclude in copy/sync (case-sensitive)"  , dest="in_exclude_files"  , metavar=("PATTERN_1", "PATTERN_2"))
parser.add_argument("-I", "--include-folders"          , default=[], action=Include_exclude_Action, nargs="*", help="Glob patterns for folders to include in copy/sync"                 , dest="in_exclude_folders", metavar=("PATTERN_1", "PATTERN_2"))
parser.add_argument("-E", "--exclude-folders"          , default=[], action=Include_exclude_Action, nargs="*", help="Glob patterns for folders to exclude in copy/sync"                 , dest="in_exclude_folders", metavar=("PATTERN_1", "PATTERN_2"))
parser.add_argument("-C", "--include-folders-case"     , default=[], action=Include_exclude_Action, nargs="*", help="Glob patterns for folders to include in copy/sync (case-sensitive)", dest="in_exclude_folders", metavar=("PATTERN_1", "PATTERN_2"))
parser.add_argument("-A", "--exclude-folders-case"     , default=[], action=Include_exclude_Action, nargs="*", help="Glob patterns for folders to exclude in copy/sync (case-sensitive)", dest="in_exclude_folders", metavar=("PATTERN_1", "PATTERN_2"))
parser.add_argument("-V", "--include-files-path"       , default=[], action=Include_exclude_Action, nargs="*", help="Absolute paths of files to include in copy/sync"                   , dest="in_exclude_files"  , metavar=("PATTERN_1", "PATTERN_2"))
parser.add_argument("-Z", "--exclude-files-path"       , default=[], action=Include_exclude_Action, nargs="*", help="Absolute paths of files to exclude in copy/sync"                   , dest="in_exclude_files"  , metavar=("PATTERN_1", "PATTERN_2"))
parser.add_argument("-Q", "--include-files-case-path"  , default=[], action=Include_exclude_Action, nargs="*", help="Absolute paths of files to include in copy/sync (case-sensitive)"  , dest="in_exclude_files"  , metavar=("PATTERN_1", "PATTERN_2"))
parser.add_argument("-w", "--exclude-files-case-path"  , default=[], action=Include_exclude_Action, nargs="*", help="Absolute paths of files to exclude in copy/sync (case-sensitive)"  , dest="in_exclude_files"  , metavar=("PATTERN_1", "PATTERN_2"))
parser.add_argument("-U", "--include-folders-path"     , default=[], action=Include_exclude_Action, nargs="*", help="Absolute paths of folders to include in copy/sync"                 , dest="in_exclude_folders", metavar=("PATTERN_1", "PATTERN_2"))
parser.add_argument("-o", "--exclude-folders-path"     , default=[], action=Include_exclude_Action, nargs="*", help="Absolute paths of folders to exclude in copy/sync"                 , dest="in_exclude_folders", metavar=("PATTERN_1", "PATTERN_2"))
parser.add_argument("-Y", "--include-folders-case-path", default=[], action=Include_exclude_Action, nargs="*", help="Absolute paths of folders to include in copy/sync (case-sensitive)", dest="in_exclude_folders", metavar=("PATTERN_1", "PATTERN_2"))
parser.add_argument("-X", "--exclude-folders-case-path", default=[], action=Include_exclude_Action, nargs="*", help="Absolute paths of folders to exclude in copy/sync (case-sensitive)", dest="in_exclude_folders", metavar=("PATTERN_1", "PATTERN_2"))
parser.add_argument("-u", "--username"                  , default=""                    , help="Remote username")
parser.add_argument("-H", "--hostname"                  , default=""                    , nargs="+", help="Remote host's address. You can specify multiple if host can appear under multiple adresses")
parser.add_argument("-p", "--password"                  , default=None                  , help="Remote password")
parser.add_argument("-y", "--key-filename"              , default=[], action="extend"   , nargs="+", type=str, help="Path to local OpenSSH private-key", dest="key_filename", metavar="KEY_FILENAME")
parser.add_argument("-P", "--port"                      , default=22, type=int          , help="Remote port (default: 22)")
parser.add_argument("-T", "--timeout"                   , default=5, type=float         , help="TCP 3-way handshake timeout in seconds (default: 5.0)", metavar="SECONDS")
parser.add_argument("-n", "--files-newer-than"          , default=""                    , help="Copy/Sync only files newer then this date"  , dest="files_newer_than"  , metavar="DATE")
parser.add_argument("-f", "--folders-newer-than"        , default=""                    , help="Copy/Sync only folders newer then this date", dest="folders_newer_than", metavar="DATE")
parser.add_argument("-R", "--recursive"                 , const=sys.maxsize, nargs="?", type=int, help='Recurse into subdirectories. Optionaly takes max recursion depth as parameter. The source and destination folders are considered as depth == 0 so specifying "--recursive 0" is the same as not specyfying it at all', dest="max_recursion_depth", metavar="MAX_RECURSION_DEPTH")
parser.add_argument("-S", "--create-dest-folder"        , action="store_true"           , help="If destination folder doesn't exists, create it and all its parents (like mkdir (-p on Linux)). If not set terminate the script if the folder doesn't exist", dest="create_dest_folder")
parser.add_argument("-x", "--create-max-rec-folders"    , action="store_true"           , help="Create empty folders at max recursion depth", dest="create_max_rec_folders")
parser.add_argument("-v", "--verbose"                   , action="store_true"           , help="Print verbose information. Good for debugging")
parser.add_argument("-s", "--silent"                    , action="store_true"           , help="Print only errors")
parser.add_argument("-t", "--dont-preserve-times"       , action="store_false"          , help="If set, modification times will not be preserved and instead files/folders will have time of copy/sync set as their modification time", dest="preserve_times")
parser.add_argument("-B", "--dont-preserve-permissions" , action="store_false"          , help="If set, permissions will not be preserved and instead files/folders will have default permissions set", dest="preserve_permissions")
parser.add_argument("-d", "--dont-close"                , action="store_true"           , help="Don't auto-close console window at the end if no error occurred. You will have to close it manually or by pressing ENTER", dest="dont_close")
parser.add_argument("-b", "--fast-remote-listdir-attr"  , action="store_true"           , help="If you copy/sync folder(s) containing more than 5000 entries from/to remote location this may be faster. Requires Python 3 on remote host", dest="fast_remote_listdir_attr")
parser.add_argument("-k", "--listdir-attr-fallback"     , action="store_true"           , help='Instead of terminating the script if remote does not have Python 3, fall back to "slow" listdir-attr. Only applicable if -b/--fast-remote-listdir-attr was set', dest="listdir_attr_fallback")
parser.add_argument("-K", "--end-on-inaccessible-entry" , action="store_true"           , help="Terminate the script if it does not have enough perrmisions to access any encountered file/folder (local or remote). If not set ignore such cases but print a warning", dest="end_on_inaccessible_entry")
parser.add_argument("-L", "--end-on-file-onto-folder"   , action="store_true"           , help="Terminate the script if a file is to be copied onto a folder and vice versa. If not set ignore such cases but print a warning", dest="end_on_file_onto_folder")
parser.add_argument("-G", "--sort-entries"              , action="store_true"           , help="Sort files/folders by name alphabetically before copying. Except for making the logs look more familiar it does not have much other use cases", dest="sort_entries")
parser.add_argument("-z", "--send2trash"                , action="store_true"           , help="When removing a file send it to trash instead. Aplies only to local due to SSH limitations")
# parser.add_argument("-u", "--dry-run"                   , action="store_true"           , help="Only create directories and disable all file copying operations and only print the output that would normally get printed", dest="dry_run")

parser.add_argument("-m", "--mode", default="copy", choices=MODE_DICT.keys(), type=str.lower, help=f'One of values: {",".join(MODE_DICT.keys())} (default: copy)')

copy_mode = parser.add_argument_group("COPY mode arguments")
copy_mode.add_argument("-F", "--force"                   , action="store_true" , help="Force copying of source files even if they are older then destination files", dest="force")
copy_mode.add_argument("-N", "--newer-than-newest-file"  , action="store_true" , help="Copy only files newer then the newest file in the destination folder", dest="newer_than_newest_file")
copy_mode.add_argument("-M", "--newer-than-newest-folder", action="store_true" , help="Copy only files newer then the newest folder in the destination folder", dest="newer_than_newest_folder")
copy_mode.add_argument("-D", "--dont-filter-dest"        , action="store_false", help="Don't filter the destination files/folders WHEN SEARCHING FOR THE NEWEST FILE", dest="filter_dest")
copy_mode.add_argument("-J", "--remove-not-in-src"       , action="store_true" , help="Remove destination files that are not present in filtered source file set", dest="remove_not_in_src")

sync_mode = parser.add_argument_group("SYNC mode arguments")
sync_mode.add_argument("-g", "--print-common-date"       , const="%Y-%m-%d %H:%M - {rel}", nargs="?", help='Before printing file transfers print the detected newest common date. Optionaly take date format string as parameter (default: "%(const)s")', dest="print_common_date", metavar="FORMAT")
sync_mode.add_argument("-j", "--common-date-from-folders", action="store_true"                      , help="Include folders when searching for newest common date", dest="common_date_from_folders")

args = parser.parse_args()

username                  : str                 = args.username
hostname                  : str                 = args.hostname
password                  : str                 = args.password
key_filename              : list  [str]         = args.key_filename
local_folder              : str                 = args.local_folder
remote_folder             : str                 = args.remote_folder
in_exclude_files          : list  [Name_filter] = args.in_exclude_files
in_exclude_folders        : list  [Name_filter] = args.in_exclude_folders
force                     : bool                = args.force
newer_than_newest_file    : bool                = args.newer_than_newest_file
newer_than_newest_folder  : bool                = args.newer_than_newest_folder
filter_dest               : bool                = args.filter_dest
max_recursion_depth       : int                 = args.max_recursion_depth
create_max_rec_folders    : bool                = args.create_max_rec_folders
verbose                   : bool                = args.verbose
silent                    : bool                = args.silent
files_newer_than          : str                 = args.files_newer_than
folders_newer_than        : str                 = args.folders_newer_than
port                      : int                 = args.port
timeout                   : float               = args.timeout
preserve_times            : bool                = args.preserve_times
preserve_permissions      : bool                = args.preserve_permissions
dont_close                : bool                = args.dont_close
mode                      : str                 = args.mode
create_dest_folder        : bool                = args.create_dest_folder
fast_remote_listdir_attr  : bool                = args.fast_remote_listdir_attr
listdir_attr_fallback     : bool                = args.listdir_attr_fallback
end_on_inaccessible_entry : bool                = args.end_on_inaccessible_entry
end_on_file_onto_folder   : bool                = args.end_on_file_onto_folder
sort_entries              : bool                = args.sort_entries
should_send2trash         : bool                = args.send2trash
remove_not_in_src         : bool                = args.remove_not_in_src
print_common_date         : str                 = args.print_common_date
common_date_from_folders  : bool                = args.common_date_from_folders
# dry_run                : bool               = args.dry_run
# endregion

# region #* PARAMETER VALIDATION
mode: int = get_mode(mode)

if max_recursion_depth is None: # -R/--recursive was not specified at all
	max_recursion_depth = 0
	if (in_exclude_folders or folders_newer_than) and not create_max_rec_folders and not silent:
		cprint("Warning: Folder filtering options don't work if -R/--recursive or -x/--create-max-rec-folders was not specified", COLOR_WARN)
elif max_recursion_depth < 0:
	raise Simple_error("-R/--recursive option's parameter cannot be negative")

if (username or hostname) and not (username and hostname):
	raise Simple_error("If any of the parameters -u/--username, -H/--hostname is specified then all of them must be specified")
REMOTE_IS_REMOTE = bool(username)

if silent and verbose:
	raise Simple_error("-s/--silent and -v/--verbose options cannot both be specified at the same time")

# Ensure paths end with "/" so os.path.abspath won't return unexpected results
local_folder = os.path.abspath(local_folder).replace("\\", "/").rstrip("/") + "/"
remote_folder = remote_folder.replace("\\", "/").rstrip("/") + "/"

DATE_FORMATS = (
	"%Y",
	"%Y-%m",
	"%Y-%m-%d",
	"%Y-%m-%d %H",
	"%Y-%m-%d %H:%M",
	"%Y-%m-%d %H:%M:%S",
)
def pre_process_files_or_folders(
		str_name: str,
		newer_than_param_name: str,
		newer_than: str,
		in_exclude: list[Name_filter],
	) -> Tuple[int, Callable[[str], bool]]:
	newer_than_date = 0
	if newer_than:
		for format in DATE_FORMATS:
			try:
				newer_than_date = datetime.strptime(newer_than, format).timestamp()
				break
			except ValueError:
				pass

		if not newer_than_date:
			raise Simple_error(f'Incorrect {newer_than_param_name} parameter: {newer_than}\nShould be in one of the formats: {", ".join(DATE_FORMATS)}')

	if verbose:
		print(f'Correctly parsed {newer_than_param_name} parameter "{newer_than}" as {datetime.fromtimestamp(newer_than_date)}')

	default_match = Include_exclude_Action.dest_defaults.get(str_name, True)

	if verbose:
		print(f'By default all {str_name}s will be {"included" if default_match else "exluded"}')

	if in_exclude:
		def match(name: str, file_path: str) -> bool:
			for filter_obj in in_exclude:
				if filter_obj.matching_func(name, file_path, filter_obj.pattern):
					return filter_obj.match_val

			return default_match
	else:
		def match(name: str, file_path: str) -> bool:
			return default_match

	return int(newer_than_date), match

files_newer_than_date  , file_match   = pre_process_files_or_folders("file"  , "-n/--files-newer-than"  , files_newer_than  , in_exclude_files  )
folders_newer_than_date, folder_match = pre_process_files_or_folders("folder", "-f/--folders-newer-than", folders_newer_than, in_exclude_folders)

#* LOCAL/REMOTE FOLDER PARAMETER VALIDATION
try:
	local_idx = sys.argv.index("-l")
except ValueError:
	local_idx = sys.argv.index("--local-folder")

try:
	remote_idx = sys.argv.index("-r")
except ValueError:
	remote_idx = sys.argv.index("--remote-folder")

LOCAL_IS_SOURCE = local_idx < remote_idx
# REMOTE_IS_SOURCE = not LOCAL_IS_SOURCE

if LOCAL_IS_SOURCE:
	source_folder = local_folder
	dest_folder   = remote_folder
else:
	source_folder = remote_folder
	dest_folder   = local_folder

# Verifying local folder
if LOCAL_IS_SOURCE or not REMOTE_IS_REMOTE:
	assert_folder_exists(source_folder)

if not LOCAL_IS_SOURCE or not REMOTE_IS_REMOTE:
	if create_dest_folder:
		ensure_folder_exists(dest_folder)
	else:
		assert_folder_exists(dest_folder, "\nYou can create it by specifying the -S/--create-dest-folder parameter")

local_remove = os.remove
if should_send2trash:
	from send2trash import send2trash
	def local_remove(path: str): send2trash(os.path.normpath(path))

def is_folder_case_sensitive_base(
	is_windows: bool,
	real_func: Callable,
	real_func_args: tuple,
	folder_type: str,
	path: str
) -> tuple[bool, bool]: # error_occured, case_sense
	if not is_windows:
		return (False, True)

	error_occured = False
	try:
		case_sense = real_func(*real_func_args)
	except Exception as e:
		error_occured = True
		if not silent:
			cprint(f'Error occured when determining if {folder_type} folder {f'"{path}"' if not verbose else ""} is case-sensitive:\n{e}', COLOR_ERROR)
		case_sense = False # Good assumption as this is the default on windows

	return (error_occured, case_sense)

if REMOTE_IS_REMOTE: # remote_folder REALLY refers to a REMOTE folder
	ssh, there_was_ssh_error = get_ssh(
		username     = username    ,
		hostnames    = hostname    ,
		password     = password    ,
		key_filename = key_filename,
		timeout      = timeout     ,
		port         = port        ,
		silent       = silent      ,
	)
	sftp = ssh.open_sftp()

	# Verifying remote folder
	if LOCAL_IS_SOURCE:
		if create_dest_folder:
			ensure_remote_folder_exists(sftp, dest_folder)
		else:
			assert_remote_folder_exists(sftp, dest_folder, "\nYou can create it by specifying the -S/--create-dest-folder parameter")
	else:
		assert_remote_folder_exists(sftp, source_folder)

	def remote_mkdir(path): return remote_mkdir_base(sftp, path)

	if fast_remote_listdir_attr and (python_str := remote_has_python(ssh, throw_on_not_found = not listdir_attr_fallback)): # don't throw if listdir_attr_fallback
		# it's only noticeably faster if one of the remote folders that will be scanned has more than 5000 entries
		rld = Remote_list_dir(ssh, python_str, init=False) # don't init the remote python script because remote_listdir_attr might not get called at all
		remote_listdir_attr = rld.listdir_attr
	else:
		if verbose and fast_remote_listdir_attr and not python_str:
			cprint('Warning: remote host does not have python. Falling back to "slow" listdir-attr', COLOR_WARN)
		def remote_listdir_attr(path: str): return tuple(sftp.listdir_iter(path)) # this is faster than sftp.listdir_attr because listdir_iter is async

	if LOCAL_IS_SOURCE:
		source_folder_iter = local_listdir_attr
		dest_folder_iter = remote_listdir_attr

		source_mkdir = local_mkdir
		dest_mkdir = remote_mkdir

		source_utime = os.utime
		dest_utime = sftp.utime

		source_chmod = os.chmod
		dest_chmod = sftp.chmod

		copy_source_dest = sftp.put
		copy_dest_source = sftp.get

		source_remove = local_remove
		dest_remove = sftp.remove

		source_rmdir = os.rmdir
		dest_rmdir = sftp.rmdir

		source_is_windows = WINDOWS
		dest_is_windows = detect_remote_os(ssh) == Os.WINDOWS

		# Only for Windows
		def is_source_folder_case_sensitive(path: str): return is_folder_case_sensitive_base(source_is_windows, is_local_folder_case_sensitive , (path, False), SOURCE_STR, path)
		def is_dest_folder_case_sensitive  (path: str): return is_folder_case_sensitive_base(dest_is_windows  , is_remote_folder_case_sensitive, (ssh , path ), DEST_STR  , path)
	else:
		source_folder_iter = remote_listdir_attr
		dest_folder_iter = local_listdir_attr

		source_mkdir = remote_mkdir
		dest_mkdir = local_mkdir

		source_utime = sftp.utime
		dest_utime = os.utime

		source_chmod = sftp.chmod
		dest_chmod = os.chmod

		copy_source_dest = sftp.get
		copy_dest_source = sftp.put

		source_remove = sftp.remove
		dest_remove = local_remove

		source_rmdir = sftp.rmdir
		dest_rmdir = os.rmdir

		source_is_windows = detect_remote_os(ssh) == Os.WINDOWS
		dest_is_windows = WINDOWS

		def is_source_folder_case_sensitive(path: str): return is_folder_case_sensitive_base(source_is_windows, is_remote_folder_case_sensitive, (ssh , path ), SOURCE_STR, path)
		def is_dest_folder_case_sensitive  (path: str): return is_folder_case_sensitive_base(dest_is_windows  , is_local_folder_case_sensitive , (path, False), DEST_STR  , path)
else: # remote_folder ACTUALLY refers to a LOCAL folder
	there_was_ssh_error = False

	source_folder_iter = local_listdir_attr
	dest_folder_iter   = local_listdir_attr

	source_mkdir = local_mkdir
	dest_mkdir   = local_mkdir

	source_utime = os.utime
	dest_utime   = os.utime

	source_chmod = os.chmod
	dest_chmod   = os.chmod

	copy_source_dest = shutil.copyfile
	copy_dest_source = shutil.copyfile

	source_remove = local_remove
	dest_remove   = local_remove

	source_rmdir = os.rmdir
	dest_rmdir   = os.rmdir

	source_is_windows = WINDOWS
	dest_is_windows   = WINDOWS

	def is_source_folder_case_sensitive(path: str): return is_folder_case_sensitive_base(source_is_windows, is_local_folder_case_sensitive, (path, False), SOURCE_STR, path)
	def is_dest_folder_case_sensitive  (path: str): return is_folder_case_sensitive_base(dest_is_windows  , is_local_folder_case_sensitive, (path, False), DEST_STR  , path)

SOURCE_DESIGNATION =  "local"  if LOCAL_IS_SOURCE  else ("remote" if REMOTE_IS_REMOTE else "local")
DEST_DESIGNATION   = ("remote" if REMOTE_IS_REMOTE else  "local") if LOCAL_IS_SOURCE  else "local"
SOURCE_DESIGNATION_PADDED = SOURCE_DESIGNATION.ljust(max(len(SOURCE_DESIGNATION), len(DEST_DESIGNATION)))
DEST_DESIGNATION_PADDED   = DEST_DESIGNATION  .ljust(max(len(SOURCE_DESIGNATION), len(DEST_DESIGNATION)))
ENTERING_OK = clr("Entering", COLOR_OK)

class My_namespace:
	def __init__(self,
		source_folder_iter,
		dest_folder_iter,
		source_mkdir,
		dest_mkdir,
		source_utime,
		dest_utime,
		source_chmod,
		dest_chmod,
		copy_source_dest,
		copy_dest_source,
		source_remove,
		dest_remove,
		source_rmdir,
		dest_rmdir,
		source_is_windows,
		dest_is_windows,
		is_source_folder_case_sensitive,
		is_dest_folder_case_sensitive,
		source_designation,
		dest_designation,
		source_designation_padded,
		dest_designation_padded,
		source_str,
		dest_str,
		source_folder_base,
		dest_folder_base,
	):
		self.source_folder_iter              : Callable = source_folder_iter
		self.dest_folder_iter                : Callable = dest_folder_iter
		self.source_mkdir                    : Callable = source_mkdir
		self.dest_mkdir                      : Callable = dest_mkdir
		self.source_utime                    : Callable = source_utime
		self.dest_utime                      : Callable = dest_utime
		self.source_chmod                    : Callable = source_chmod
		self.dest_chmod                      : Callable = dest_chmod
		self.copy_source_dest                : Callable = copy_source_dest
		self.copy_dest_source                : Callable = copy_dest_source
		self.source_remove                   : Callable = source_remove
		self.dest_remove                     : Callable = dest_remove
		self.source_rmdir                    : Callable = source_rmdir
		self.dest_rmdir                      : Callable = dest_rmdir
		self.source_is_windows               : Callable = source_is_windows
		self.dest_is_windows                 : Callable = dest_is_windows
		self.is_source_folder_case_sensitive : Callable = is_source_folder_case_sensitive
		self.is_dest_folder_case_sensitive   : Callable = is_dest_folder_case_sensitive
		self.source_designation              : str = source_designation
		self.dest_designation                : str = dest_designation
		self.source_designation_padded       : str = source_designation_padded
		self.dest_designation_padded         : str = dest_designation_padded
		self.source_str                      : str = source_str
		self.dest_str                        : str = dest_str
		self.source_folder_base              : str = source_folder_base
		self.dest_folder_base                : str = dest_folder_base

normal_ns = My_namespace(
	source_folder_iter              = source_folder_iter,
	dest_folder_iter                = dest_folder_iter,
	source_mkdir                    = source_mkdir,
	dest_mkdir                      = dest_mkdir,
	source_utime                    = source_utime,
	dest_utime                      = dest_utime,
	source_chmod                    = source_chmod,
	dest_chmod                      = dest_chmod,
	copy_source_dest                = copy_source_dest,
	copy_dest_source                = copy_dest_source,
	source_remove                   = source_remove,
	dest_remove                     = dest_remove,
	source_rmdir                    = source_rmdir,
	dest_rmdir                      = dest_rmdir,
	source_is_windows               = source_is_windows,
	dest_is_windows                 = dest_is_windows,
	is_source_folder_case_sensitive = is_source_folder_case_sensitive,
	is_dest_folder_case_sensitive   = is_dest_folder_case_sensitive,
	source_designation              = SOURCE_DESIGNATION,
	dest_designation                = DEST_DESIGNATION,
	source_designation_padded       = SOURCE_DESIGNATION_PADDED,
	dest_designation_padded         = DEST_DESIGNATION_PADDED,
	source_str                      = SOURCE_STR,
	dest_str                        = DEST_STR,
	source_folder_base              = source_folder,
	dest_folder_base                = dest_folder,
)
reverse_ns = My_namespace(
	source_folder_iter              = dest_folder_iter,
	dest_folder_iter                = source_folder_iter,
	source_mkdir                    = dest_mkdir,
	dest_mkdir                      = source_mkdir,
	source_utime                    = dest_utime,
	dest_utime                      = source_utime,
	source_chmod                    = dest_chmod,
	dest_chmod                      = source_chmod,
	copy_source_dest                = copy_dest_source,
	copy_dest_source                = copy_source_dest,
	source_remove                   = dest_remove,
	dest_remove                     = source_remove,
	source_rmdir                    = dest_rmdir,
	dest_rmdir                      = source_rmdir,
	source_is_windows               = dest_is_windows,
	dest_is_windows                 = source_is_windows,
	is_source_folder_case_sensitive = is_dest_folder_case_sensitive,
	is_dest_folder_case_sensitive   = is_source_folder_case_sensitive,
	source_designation              = DEST_DESIGNATION,
	dest_designation                = SOURCE_DESIGNATION,
	source_designation_padded       = DEST_DESIGNATION_PADDED,
	dest_designation_padded         = SOURCE_DESIGNATION_PADDED,
	source_str                      = DEST_STR,
	dest_str                        = SOURCE_STR,
	source_folder_base              = dest_folder,
	dest_folder_base                = source_folder,
)

DEST_FILTER_WARN = verbose and filter_dest and any(filter(lambda f: f.matching_func is fnmatchcase, in_exclude_files + in_exclude_folders))

# Preserving permissions is only sensible when copying files between Unix machines as Windows has
# different permission system, incompatible with Unix
preserve_permissions = preserve_permissions and not source_is_windows and not dest_is_windows
# endregion

# region #* FILE COPYING
REMOVE_COLOR = COLOR_EMPHASIS
def recursive_remove(
	folder_path: str,
	entry: paramiko.SFTPAttributes,
	iter_fun: Callable,
	remove_file_fun: Callable,
	remove_folder_fun: Callable,
	designation: str,
	type: str,
):
	base_path = posixpath.join(folder_path, entry.filename)
	if is_file(entry):
		try:
			remove_file_fun(base_path)
			if not silent:
				cprint(f"Removed: {base_path}", REMOVE_COLOR)
		except Exception as e:
			permission_error_handler(e, designation, type, base_path, "file", "deleting")
	elif is_dir(entry):
		try:
			entries = iter_fun(base_path)
		except Exception as e:
			permission_error_handler(e, designation, type, base_path)
			return

		for entry in entries:
			recursive_remove(base_path, entry, iter_fun, remove_file_fun, remove_folder_fun, designation, type)

		try:
			remove_folder_fun(base_path)
			if not silent:
				cprint(f"Removed: {base_path}", REMOVE_COLOR)
		except Exception as e:
			permission_error_handler(e, designation, type, base_path, "folder", "deleting")

def file_on_folder_error_handler(entry: paramiko.SFTPAttributes):
	txt = f'Warning: tried copying a {'file' if is_file(entry) else 'folder'} onto a {'folder' if is_file(entry) else 'file'} with a name "{entry.filename}"'
	if end_on_file_onto_folder:
		raise Simple_error(txt)
	else:
		if not silent:
			cprint(txt, COLOR_WARN)

def permission_error_handler(err: Exception, designation: str, type: str, path: str, file_folder = "folder", operation = "listing"):
	# This is not the best way to correctly identify permission errors but it needs to be this way
	# because of inconsistencies in OSes and SSH server implementations. On Windows running OpenSSH I
	# observed that when logged as non admin and trying to listdir admin's folder the server returns
	# "Bad message" text. On Termux on Android running OpenSSH when listdir'ing the root folder "/"
	# the server returns "Failure" text. I think the servers should return the SFTP_PERMISSION_DENIED
	# error code so the error could be casted to PermissionError by paramiko but it is what it is...
	if err is PermissionError or (err is IOError and (error_msg := str(err)) and (error_msg == "Failure" or error_msg == "Bad message")):
		txt = f'Warning: permission denied when {operation} the {designation} {type} {file_folder} "{path}"'
		if end_on_inaccessible_entry:
			raise Simple_error(txt)
		else:
			if not silent:
				cprint(txt, COLOR_WARN)
	else:
		raise err

class Filter_class:
	def __init__(self, source_folder_param, source_folder_base, recursion_ok):
		self.source_folder_param = source_folder_param
		self.source_folder_base = source_folder_base
		self.recursion_ok = recursion_ok

	def _inner_filter_fun(self, entry: paramiko.SFTPAttributes) -> bool:
		# ___NewerThanDate comparisons use the < operator so if the user inputs exact modification date
		# of some file/folder that file/folder will not be included in the operations
		file_path = posixpath.join(self.source_folder_param, entry.filename)
		return is_file(entry)                       and files_newer_than_date   < entry.st_mtime and file_match  (entry.filename, file_path) \
		    or is_dir (entry) and self.recursion_ok and folders_newer_than_date < entry.st_mtime and folder_match(entry.filename, file_path)

	def __call__(self, entry: paramiko.SFTPAttributes) -> bool:
		val = self._inner_filter_fun(entry)

		if not val:
			name = entry.filename
			file_path = posixpath.join(self.source_folder_param, entry.filename)
			rel_path = file_path.replace(self.source_folder_base, "", 1)
			if is_file(entry):
				if not (files_newer_than_date <= entry.st_mtime):
					print(f'{rel_path} - skipping file because it ({modified_date(entry)}) is not newer than -n/--files-newer-than parameter')
				elif not file_match(name, file_path):
					print(f"{rel_path} - skipping file because file_match returned False")
				else:
					cprint(f"{rel_path} - skipping file because of unknown reason", COLOR_ERROR) # Shouldn't happen
			elif is_dir(entry):
				if not self.recursion_ok:
					print(f"{rel_path} - skipping folder because we are at max recursion depth and create_max_rec_folders is False")
				elif not (folders_newer_than_date <= entry.st_mtime):
					print(f'{rel_path} - skipping folder because it ({modified_date(entry)}) is not newer than -f/--folders-newer-than parameter')
				elif not folder_match(name, file_path):
					print(f"{rel_path} - skipping folder because folder_match returned False")
				else:
					cprint(f"{rel_path} - skipping folder because of unknown reason", COLOR_ERROR) # Shouldn't happen
			else:
				print(f"{rel_path} - skipping because it is not a file nor folder")

		return val

if not verbose:
	Filter_class.__call__ = Filter_class._inner_filter_fun

def check_case_duplicates(
	entries_list: list[paramiko.SFTPAttributes],
	source_error_occured: bool,
	dest_error_occured: bool,
	designation: str,
	type: str,
	path: str
) -> list[paramiko.SFTPAttributes]:
	""" Check for case-insensitive filename duplicates and exclude them from copy/sync operations """
	caseless_entries = defaultdict(list)
	for entry in entries_list:
		caseless_entries[entry.filename.lower()].append(entry)

	case_duplicates: list[list[paramiko.SFTPAttributes]] = []
	for entries in caseless_entries.values():
		if len(entries) > 1:
			case_duplicates.append(entries)

	if case_duplicates:
		if not silent:
			print(f'Following files/folders in the {designation} {type} folder "{path}" have names that only differ in letter case:')
			for i, entries in enumerate(case_duplicates, start=1):
				print(f"Group {i}:")
				for entry in entries:
					print(entry.filename)
			cprint(f"And they will not be copied unless you change their names or enable case-sensitivity in the destination Windows folder with fsutil.exe", COLOR_WARN)
		case_duplicates_flattened = tuple(chain.from_iterable(case_duplicates))
		entries_list = tuple(filter(lambda e: e not in case_duplicates_flattened, entries_list))
	elif source_error_occured or dest_error_occured:
		if not silent:
			cprint(f"...but it won't cause any problems because {designation} {type} files/folders are case-sensitivly unique", COLOR_OK)

	return entries_list

def recursive_copy_helper(
	source_entry: paramiko.SFTPAttributes,
	source_folder_param: str,
	dest_entry: paramiko.SFTPAttributes,
	dest_folder_param: str,
	depth: int,
	NNS: My_namespace,
	RNS: My_namespace,
	force: bool = False,
	newest_dest_date: int = 0,
) -> Action:
	# In the following code posixpath.join is used correctly with case-sensitive name because:
	#    1. Windows accepts forward slashes "/" as path separators
	#    2. Windows paths are case-insensitive but case preserving so it will normalize the path before accessing the FS
	source_name = source_entry.filename
	dest_name = dest_entry.filename if dest_entry else source_name

	if not silent:
		rel_path = posixpath.join(source_folder_param, source_name).replace(NNS.source_folder_base, "", 1)

	if is_file(source_entry) and newest_dest_date < source_entry.st_mtime:
		if dest_entry and is_dir(dest_entry):
			file_on_folder_error_handler(source_entry)
			return Action.CONTINUE # because in MODE.SYNC next function call would raise the same exception

		if force or not dest_entry or dest_entry.st_mtime < source_entry.st_mtime:
			source_path = posixpath.join(source_folder_param, source_name)
			dest_path   = posixpath.join(dest_folder_param  , dest_name  )

			if not silent:
				if mode == Mode.SYNC:
					cprint(f"{'source -> destination' if NNS is normal_ns else 'destination -> source'}: {rel_path}", COLOR_OK)
				else: # MODE.COPY
					cprint(rel_path, COLOR_OK)

			try:
				NNS.copy_source_dest(source_path, dest_path)
			except Exception as e:
				permission_error_handler(e, NNS.dest_designation, NNS.dest_str, dest_path)
				return Action.RETURN # because every next file would raise the same exception

			if preserve_times:
				NNS.dest_utime(dest_path, (source_entry.st_atime, source_entry.st_mtime))

			if preserve_permissions and (not dest_entry or source_entry.st_mode != dest_entry.st_mode):
				NNS.dest_chmod(dest_path, source_entry.st_mode)
		elif verbose:
			if not (dest_entry.st_mtime < source_entry.st_mtime):
				print(f"{rel_path} - skipping file because it is not newer than the {NNS.dest_str}")
			else:
				cprint(f"{rel_path} - skipping file because of unknown reason", COLOR_ERROR) # Shouldn't happen
	elif is_dir(source_entry):
		if dest_entry and is_file(dest_entry):
			file_on_folder_error_handler(source_entry)
			return Action.CONTINUE

		new_dest_folder = posixpath.join(dest_folder_param, dest_name)
		if not dest_entry:
			NNS.dest_mkdir(new_dest_folder)

		if preserve_permissions and (not dest_entry or source_entry.st_mode != dest_entry.st_mode):
			NNS.dest_chmod(new_dest_folder, source_entry.st_mode)

		if depth < max_recursion_depth:
			new_source_folder = posixpath.join(source_folder_param, source_name)
			recursive_copy(
				source_folder_param = new_source_folder,
				dest_folder_param   = new_dest_folder,
				NNS = NNS,
				RNS = RNS,
				depth = depth + 1,
			)

		if preserve_times: # We cannot set the time conditionally as putting any files inside the folder updated it modification date
			NNS.dest_utime(new_dest_folder, (source_entry.st_atime, source_entry.st_mtime))

		return Action.CONTINUE # so te recursion doesn't happen on the next function call
	elif verbose:
		if is_file(source_entry):
			if not (newest_dest_date < source_entry.st_mtime):
				print(f"{rel_path} - skipping file because it ({modified_date(source_entry)}) is not newer than newest_dest_date")
			else:
				cprint(f"{rel_path} - skipping file because of unknown reason", COLOR_ERROR) # Shouldn't happen

	return Action.NONE

def recursive_copy(
	source_folder_param: str,
	dest_folder_param: str,
	NNS: My_namespace,
	RNS: My_namespace,
	depth: int = 0
):
	if verbose:
		print(f"{ENTERING_OK} {NNS.source_designation_padded} source      folder: {source_folder_param}")
		print(f"{ENTERING_OK} {NNS.dest_designation_padded  } destination folder: {dest_folder_param}")

	filter_fun = Filter_class(source_folder_param, NNS.source_folder_base, recursion_ok = depth < max_recursion_depth or create_max_rec_folders)

	match mode:
		case Mode.COPY:
			try:
				source_entries: tuple[paramiko.SFTPAttributes] = tuple(filter(filter_fun, NNS.source_folder_iter(source_folder_param)))
			except Exception as e:
				permission_error_handler(e, NNS.source_designation, NNS.source_str, source_folder_param)
				return

			if not source_entries and not remove_not_in_src: return

			source_error_occured, source_case_sense = NNS.is_source_folder_case_sensitive(source_folder_param)
			dest_error_occured  , dest_case_sense   = NNS.is_dest_folder_case_sensitive  (dest_folder_param  )
			ALL_CASE_SENSITIVE = source_case_sense and dest_case_sense

			if source_case_sense and not dest_case_sense: # Most probable scenario: copy from Linux to Windows
				source_entries = check_case_duplicates(source_entries, source_error_occured, dest_error_occured, NNS.source_designation, NNS.source_str, source_folder_param)
				if not source_entries and not remove_not_in_src: return

			if sort_entries:
				source_entries = sorted(source_entries, key=lambda x: x.filename)

			try:
				dest_entries: list[paramiko.SFTPAttributes] = NNS.dest_folder_iter(dest_folder_param)
			except Exception as e:
				permission_error_handler(e, NNS.dest_designation, NNS.dest_str, dest_folder_param)
				return

			newest_dest_date = 0
			if source_entries and (newer_than_newest_file or newer_than_newest_folder): # find newest file/folder in the destination folder
				if DEST_FILTER_WARN and not dest_case_sense:
					cprint("Warning: When searching for newest file in the destination folder you may have excluded some files/folders case-sensitivly but the destination folder is case-insensitive", COLOR_WARN)

				entry_count = 0
				for entry in (filter(filter_fun._inner_filter_fun, dest_entries) if filter_dest else dest_entries):
					if newer_than_newest_file and is_file(entry) or newer_than_newest_folder and is_dir(entry):
						entry_count += 1
						if newest_dest_date < entry.st_mtime:
							newest_dest_date = entry.st_mtime

				if verbose:
					matching = " matching" if filter_dest else ""
					files_folders = "files/folders" if newer_than_newest_file and newer_than_newest_folder else ("files" if newer_than_newest_file else "folders")
					the_newest = f"and the newest from them has date {datetime.fromtimestamp(newest_dest_date)} -> newest_dest_date" if entry_count else ""
					print(f"Destination folder has {entry_count}{matching} {files_folders} {the_newest}")

			# If any of the locations is case-insensitive we have to normalize the case as that is more intuitive
			if ALL_CASE_SENSITIVE: dest_entries_dict = {entry.filename        : entry for entry in dest_entries}
			else                 : dest_entries_dict = {entry.filename.lower(): entry for entry in dest_entries}

			if remove_not_in_src and dest_entries:
				if ALL_CASE_SENSITIVE:
					source_names = {entry.filename for entry in source_entries}
				else:
					source_names = {entry.filename.lower() for entry in source_entries}
				for filename, dest_entry in dest_entries_dict.items(): # We iterate over dest_entries_dict because it has case normalized names if not ALL_CASE_SENSITIVE
					if filename not in source_names:
						recursive_remove(dest_folder_param, dest_entry, NNS.dest_folder_iter, NNS.dest_remove, NNS.dest_rmdir, NNS.dest_designation, NNS.dest_str)

			for source_entry in source_entries:
				name = source_entry.filename
				match recursive_copy_helper(
					source_entry        = source_entry,
					dest_entry          = dest_entries_dict.get(name if ALL_CASE_SENSITIVE else name.lower()),
					source_folder_param = source_folder_param,
					dest_folder_param   = dest_folder_param,
					depth               = depth,
					NNS                 = NNS,
					RNS                 = RNS,
					force               = force,
					newest_dest_date    = newest_dest_date,
				):
					case Action.RETURN: return
		case Mode.SYNC:
			try:
				source_entries_base: list[paramiko.SFTPAttributes] = NNS.source_folder_iter(source_folder_param)
			except Exception as e:
				permission_error_handler(e, NNS.source_designation, NNS.source_str, source_folder_param)
				return

			try:
				dest_entries_base: list[paramiko.SFTPAttributes] = NNS.dest_folder_iter(dest_folder_param)
			except Exception as e:
				permission_error_handler(e, NNS.dest_designation, NNS.dest_str, dest_folder_param)
				return

			source_entries = tuple(filter(filter_fun, source_entries_base))
			dest_entries   = tuple(filter(filter_fun, dest_entries_base  ))

			if not (source_entries or dest_entries): return

			source_error_occured, source_case_sense = NNS.is_source_folder_case_sensitive(source_folder_param)
			dest_error_occured  , dest_case_sense   = NNS.is_dest_folder_case_sensitive  (dest_folder_param  )

			if not source_case_sense or not dest_case_sense:
				source_entries = check_case_duplicates(source_entries, source_error_occured, dest_error_occured, NNS.source_designation, NNS.source_str, source_folder_param)
				dest_entries   = check_case_duplicates(dest_entries  , source_error_occured, dest_error_occured, NNS.dest_designation  , NNS.dest_str  , dest_folder_param  )

				if not (source_entries or dest_entries): return

				source_entries_dict_base = {entry.filename.lower(): entry for entry in source_entries_base}
				dest_entries_dict_base   = {entry.filename.lower(): entry for entry in dest_entries_base  }
				source_entries_dict      = {entry.filename.lower(): entry for entry in source_entries     }
				dest_entries_dict        = {entry.filename.lower(): entry for entry in dest_entries       }
			else:
				source_entries_dict_base = {entry.filename: entry for entry in source_entries_base}
				dest_entries_dict_base   = {entry.filename: entry for entry in dest_entries_base  }
				source_entries_dict      = {entry.filename: entry for entry in source_entries     }
				dest_entries_dict        = {entry.filename: entry for entry in dest_entries       }

			all_names = source_entries_dict.keys() | dest_entries_dict.keys()

			if sort_entries:
				all_names = sorted(all_names)

			newest_common_date = 0
			all_entries: List[Tuple[paramiko.SFTPAttributes, paramiko.SFTPAttributes, str]] = []
			for name in all_names:
				source_entry = source_entries_dict.get(name)
				dest_entry   = dest_entries_dict  .get(name)
				all_entries.append((source_entry, dest_entry, name)) # We save the name because it might have been .lower()ed
				if source_entry and dest_entry and (is_file(source_entry) or common_date_from_folders and is_dir(source_entry)) and source_entry.st_mtime == dest_entry.st_mtime:
					if newest_common_date < source_entry.st_mtime:
						newest_common_date = source_entry.st_mtime

			if print_common_date and not silent:
				print(f".{source_folder_param.replace(NNS.source_folder_base, "", 1) or "/"}: Newest common date: { \
					datetime.fromtimestamp(newest_common_date).strftime(print_common_date).format(rel = get_rel_time(newest_common_date))}")

			for source_entry, dest_entry, name in all_entries:
				# When source_entry is None source_entry_base might not be None (because i.e. folders where
				# filetered out or entries where filtered case-sensitively while the folders are
				# case-insensitive). That's why we need to get it from the dict and check it. The same
				# applies to dest_entry and dest_entry_base.

				# When source_entry is not None and source_entry_base is not None then they should refer to
				# the same object so source_entry is source_entry_base == True
				source_entry_base = source_entries_dict_base.get(name)
				dest_entry_base   = dest_entries_dict_base  .get(name)

				if source_entry:
					if not dest_entry_base and source_entry.st_mtime < newest_common_date:
						recursive_remove(source_folder_param, source_entry, NNS.source_folder_iter, NNS.source_remove, NNS.source_rmdir, NNS.source_designation, NNS.source_str)
					else:
						match recursive_copy_helper(
							source_entry        = source_entry,
							dest_entry          = dest_entry_base,
							source_folder_param = source_folder_param,
							dest_folder_param   = dest_folder_param,
							depth               = depth,
							NNS                 = NNS,
							RNS                 = RNS,
						):
							case Action.CONTINUE: continue
							case Action.RETURN: return
				if dest_entry:
					if not source_entry_base and dest_entry.st_mtime < newest_common_date:
						recursive_remove(dest_folder_param, dest_entry, NNS.dest_folder_iter, NNS.dest_remove, NNS.dest_rmdir, NNS.dest_designation, NNS.dest_str)
					else:
						match recursive_copy_helper(
							source_entry        = dest_entry,
							dest_entry          = source_entry_base,
							source_folder_param = dest_folder_param,
							dest_folder_param   = source_folder_param,
							depth               = depth,
							NNS                 = RNS,
							RNS                 = NNS,
						):
							case Action.CONTINUE: continue
							case Action.RETURN: return

if not silent:
	match mode:
		case Mode.COPY: operation = "Copying"
		case Mode.SYNC: operation = "Syncing"

	print(f"{operation} from {SOURCE_DESIGNATION} to {DEST_DESIGNATION}")
	print(f"Source      folder: {source_folder}")
	print(f"Destination folder: {dest_folder}")
	print(f"{operation} files:\n")

recursive_copy(
	source_folder_param = source_folder,
	dest_folder_param   = dest_folder,
	NNS = normal_ns,
	RNS = reverse_ns,
	depth = 0,
)

# the try...finally block is not needed because when an exception happens "the program ends, the
# Python process shuts down. As part of process teardown, the underlying socket to the SSH server is
# closed by the OS"
if REMOTE_IS_REMOTE:
	sftp.close()
	ssh.close()

if not silent:
	print(f"\nExecution time: {perf_counter() - start:.3f} s")

if dont_close or there_was_ssh_error:
	if silent:
		input("")
	else:
		input(clr("\nPress ENTER to continue...", COLOR_OK))
# endregion
