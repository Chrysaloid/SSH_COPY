import sys; from pathlib import Path; p = Path(__file__).resolve().parent; __package__ = p.name; sys.path.append(p.parent.as_posix()) # To be able to use relative imports

from argparse import Namespace
from datetime import datetime
from enum import auto, IntEnum
from fnmatch import fnmatchcase
from functools import partial as bindKwarg
from operator import attrgetter as getAttr, itemgetter as getItem
import os
import shutil
from time import perf_counter
from typing import Callable, Tuple

from termcolor import colored as clr, cprint

from .argparse_utils import ArgumentParser_colored_error, COMMON_FORMATTER_CLASS
from .file_utils import assert_folder_exists as assert_local_folder_exists, is_dir
from .local_sftp_attributes import local_listdir_attr, Local_SFTPAttributes
from .print_rel_time import get_rel_time
from .simple_error import Simple_error
from .ssh_utils import assert_remote_folder_exists, get_ssh, Os, parse_os_str, Remote_list_dir

"""
Edge cases that were disregarded:
- case-insensitivity of file names on Windows - use `fsutil file setCaseSensitiveInfo "C:/path to folder" enable` to enable case-sensitivity for your folder(s)
- caching of directory listings - while it speeds up the copying process it may result in omitting some files in more complex setups that's why it's disabled by default and you can enable it using --cache-directory-listings flag
- this script is supposed to be simple so no recursion is performed
"""

def print_return(thing):
	print(thing)
	return thing

class Padded_IntEnum(IntEnum):
	def __init_subclass__(cls, **kwargs):
		super().__init_subclass__(**kwargs)

		max_len = max(len(member.name) for member in cls)

		for member in cls:
			member._padded_name_ = member.name.ljust(max_len)
			member._name_lower_ = member.name.lower()

	@classmethod
	def parse_member(cls, txt: str):
		txt = txt.lower().strip()

		for member in cls:
			if txt == member._name_lower_ or txt == member._name_lower_[0]:
				return member

		raise Simple_error(f"Invalid {cls.name}: {txt}")

class Mode(Padded_IntEnum):
	SYNC     = auto()
	COPY     = auto()
	DEL_COPY = auto()
	MOVE     = auto()

class Place(Padded_IntEnum):
	LOCAL = auto()
	REMOTE = auto()

def parse_bool(txt: str, name = "bool") -> bool:
	match txt.lower().strip():
		case "1" | "true" | "t" | "yes" | "yeah" | "yup" | "tak" | "on": return True
		case "0" | "false" | "f" | "no" | "nah" | "nope" | "nie" | "off": return False
		case _: raise Simple_error(f"Invalid {name}: {txt}")

def parse_file_pattern(txt: str):
	file_pattern, file_pattern_bool = txt.split("/", 1)
	return (file_pattern, parse_bool(file_pattern_bool, "file_pattern_bool"))

class Call_accumulator:
	def __init__( self, ) -> None:
		self.args = []

	def __call__(self, *args) -> None:
		self.args.append(args)
		return self

	def __repr__(self):
		return f"Call_accumulator(calls={self.args})"

def filter_fun(file: Local_SFTPAttributes, file_patterns: Tuple[Tuple[str, bool], ...], default_match: bool) -> bool:
	if is_dir(file): return False # this script is supposed to be simple so no recursion is performed

	for pattern, match_val in file_patterns:
		if fnmatchcase(file.filename, pattern):
			return match_val

	return default_match

def normalize_local_folder_path(local_folder: str) -> str:
	return os.path.abspath(local_folder).replace("\\", "/").rstrip("/") + "/"

def normalize_remote_folder_path(remote_folder: str) -> str:
	return remote_folder.replace("\\", "/").rstrip("/") + "/"

def path_join(folder, file):
	return folder + file

magenta_source = clr("Source", "magenta")
cyan_dest = clr("Dest", "cyan")
magenta_s = clr("S", "magenta")
cyan_d = clr("D", "cyan")

BLUE_COLOR = "light_blue"

def main(args: Namespace = None):
	start = perf_counter()

	args_from_cli = not bool(args)

	if args_from_cli:
		parser = ArgumentParser_colored_error(
			description="Copy, move or sync files between folders on remote or local machines",
			formatter_class=COMMON_FORMATTER_CLASS,
		)

		required = parser.add_argument_group("Required arguments")
		parser._action_groups = [required, parser._optionals]

		required.add_argument(
			"-o",
			"--operation",
			required=True,
			action="append",
			nargs=7,
			metavar=(
				"SOURCE_DIR",
				"SOURCE_PLACE",
				"DEST_DIR",
				"DEST_PLACE",
				"MODE",
				"FILE_PATTERNS",
				"DEFAULT_MATCH"
			),
			help="Operation to perform. Can be specified multiple times",
			dest="operations",
		)
		required.add_argument("-u", "--username", required=False, default="", help="Remote username")
		required.add_argument("-H", "--hostname", required=False, default="", nargs="*", help="Remote host's address. You can specify multiple if host can appear under multiple adresses")
		required.add_argument("-S", "--hosts"   , required=False, default="", nargs="*", help="Remote hosts to try (i.e. user@192.168.0.123:1234). You can specify multiple if host can appear under multiple adresses. Takes precedence over others")

		parser._optionals.title = "Optional arguments"

		parser.add_argument("-p", "--password"                , default=None         , help="Remote password")
		parser.add_argument("-P", "--port"                    , default=22, type=int , help="Remote port (default: 22)")
		parser.add_argument("-T", "--timeout"                 , default=5, type=float, help="TCP 3-way handshake timeout in seconds (default: 5.0)", metavar="SECONDS")
		parser.add_argument("-v", "--verbose"                 , action="store_true"  , help="Print verbose information. Good for debugging")
		parser.add_argument("-s", "--silent"                  , action="store_true"  , help="Print only errors")
		parser.add_argument("-d", "--dry-run"                 , action="store_true"  , help="Do not perform any copying and just print the information that would normally be printed. Good for testing", dest="dry_run")
		parser.add_argument("-O", "--remote-os"               , default="auto"       , help="Remote host's operating system. Can be (a, auto, auto-detect) or (w, win, windows) or (u, unix, l, linux, p, posix) or (m, mac, macos, darwin) or (t, termux) or (n, android) or (b, bsd, freebsd, openbsd, netbsd, dragonfly) or (s, solaris, sunos, illumos). Windows just needs to be handled in a special way so we need to differentiate it from the others. Auto will run a few commands on the remote machine to determine it's OS and they are not 100%% relaible so if you know the remote's OS and want to save time you can use this argument (default: auto)", dest="remote_os")
		parser.add_argument("-c", "--cache-directory-listings", action="store_true"  , help="Listing all entries in a directory is a bit expensive operation so caching speeds up the copying process but it may result in omitting some files in more complex setups (i.e. for folders [A: 1 file, B: empty, C: empty] and operations ['copy from A to B', 'copy from B to C'] running the script would result in folder C still being empty because cached empty listing of folder B would be used in the second operation). To reduce confusion the caching is disabled by default and you have to enable it using this flag", dest="cache_directory_listings")

		args = parser.parse_args()

	operations               : list  [list[str]] = args.operations
	username                 : str               = args.username
	hostname                 : list[str]         = args.hostname
	hosts                    : list[str]         = args.hosts
	password                 : str               = args.password
	port                     : int               = args.port
	timeout                  : float             = args.timeout
	verbose                  : bool              = args.verbose
	silent                   : bool              = args.silent
	dry_run                  : bool              = args.dry_run
	remote_os                : str               = args.remote_os
	cache_directory_listings : bool              = args.cache_directory_listings

	if silent and verbose:
		raise Simple_error("-s/--silent and -v/--verbose options cannot both be specified at the same time")

	if (not username and not hostname and not hosts) or (hostname and not username) or (username and not hostname):
		raise Simple_error("Either -u/--username and -H/--hostname or -S/--hosts needs to be specified")

	if args_from_cli:
		parsed_operations = []
		for source_dir, source_place, dest_dir, dest_place, mode, file_patterns, default_match in operations:
			source_place = Place.parse_member(source_place)
			dest_place   = Place.parse_member(dest_place)
			if source_place == Place.LOCAL: assert_local_folder_exists(source_dir)
			if dest_place   == Place.LOCAL: assert_local_folder_exists(dest_dir)
			mode          = Mode.parse_member(mode)
			file_patterns = tuple(map(parse_file_pattern, file_patterns.split("|"))) if file_patterns else []
			default_match = parse_bool(default_match, "default_match")
			parsed_operations.append((source_dir, source_place, dest_dir, dest_place, mode, file_patterns, default_match))
	else:
		parsed_operations = operations

	ssh, there_was_ssh_error = get_ssh(
		username  = username,
		hostnames = hostname,
		password  = password,
		hosts     = hosts   ,
		timeout   = timeout ,
		port      = port    ,
		silent    = silent  ,
	)
	sftp = ssh.open_sftp()

	REMOTE_IS_WINDOWS = parse_os_str(remote_os, ssh) == Os.WINDOWS

	if verbose: print(f"Remote OS is {"Windows" if REMOTE_IS_WINDOWS else "not Windows"}")

	class Remote_copy_batch:
		def __init__(
			self,
			source_dir: str,
			dest_dir: str,
			command: str,
			print_files = False,
			print_color = "green",
		) -> None:
			self.files: list[str] = []
			self.source_dir = source_dir
			self.dest_dir = dest_dir
			self.command = command
			self.print_files = print_files
			self.print_color = print_color

		def __call__(self, filename: str, _) -> None:
			self.files.append(filename)

		def finalize(self) -> None:
			if not self.files:
				return

			if not dry_run:
				stdin, stdout, stderr = ssh.exec_command(f'cd {"/d" if REMOTE_IS_WINDOWS else ""} "{self.source_dir}" && xargs -0 {self.command} -t "{self.dest_dir}"')

				if self.print_files and not silent and not isinstance(self.files, (list, tuple)): # nenecessary because self.files might be an iterable
					self.files = tuple(self.files)

				stdin.write("\0".join(self.files).replace(self.dest_dir, "") + "\0")
				stdin.channel.shutdown_write()

				exit_code = stdout.channel.recv_exit_status()

				if exit_code != 0:
					raise RuntimeError(f"Remote copy failed:\n{stdout.read().decode()}\n{stderr.read().decode()}")

			if self.print_files and not silent:
				cprint("\n".join(self.files), self.print_color)

	def filter_fun(file: Local_SFTPAttributes, file_patterns: Tuple[Tuple[str, bool], ...], default_match: bool) -> bool:
		if is_dir(file): return False # this script is supposed to be simple so no recursion is performed

		for pattern, match_val in file_patterns:
			if fnmatchcase(file.filename, pattern):
				return match_val

		return default_match

	def sync_fun(source_files: dict[str, Local_SFTPAttributes], source_place: Place, dest_files: dict[str, Local_SFTPAttributes], dest_place: Place, source_dir: str, dest_dir: str):
		if source_place == Place.LOCAL and dest_place == Place.LOCAL:
			copy_source_dest = bindKwarg(shutil.copyfile, follow_symlinks=False)
			copy_dest_source = copy_source_dest
			utime_dest       = os.utime
			utime_source     = os.utime
			remove_dest      = os.remove
			remove_source    = os.remove
		elif source_place == Place.REMOTE and dest_place == Place.LOCAL:
			copy_source_dest = sftp.get
			copy_dest_source = bindKwarg(sftp.put, confirm=False)
			utime_dest       = os.utime
			utime_source     = sftp.utime
			remove_dest      = os.remove
			remove_source    = sftp.remove
		elif source_place == Place.LOCAL and dest_place == Place.REMOTE:
			copy_source_dest = bindKwarg(sftp.put, confirm=False)
			copy_dest_source = sftp.get
			utime_dest       = sftp.utime
			utime_source     = os.utime
			remove_dest      = sftp.remove
			remove_source    = os.remove
		elif source_place == Place.REMOTE and dest_place == Place.REMOTE:
			copy_source_dest = Remote_copy_batch(source_dir, dest_dir, "cp -u", False)
			copy_dest_source = Remote_copy_batch(dest_dir, source_dir, "cp -u", False)
			utime_dest       = Call_accumulator()
			utime_source     = Call_accumulator()
			remove_dest      = sftp.remove
			remove_source    = sftp.remove

		newest_common_date = 0 # start from smallest (reasonably) possible date
		for filename in source_files.keys() & dest_files.keys(): # common keys
			source_file = source_files[filename]
			if newest_common_date < source_file.st_mtime and source_file.st_mtime == dest_files[filename].st_mtime:
				newest_common_date = source_file.st_mtime

		if not silent:
			print(f"""# Newest common date: {
				datetime.fromtimestamp(newest_common_date)
				.strftime('%Y-%m-%d %H:%M:%S - {rel}')
				.format(rel = get_rel_time(newest_common_date)) if newest_common_date else clr("None because there are no common files", "yellow")
			}""")

		for filename in source_files.keys() | dest_files.keys(): # all keys
			source_file = source_files.get(filename)
			dest_file   = dest_files  .get(filename)

			if source_file and dest_file:
				if source_file.st_mtime > dest_file.st_mtime:                               # Case 1
					if not silent: print(f"{magenta_s} -> {cyan_d}: {clr(filename, "green")}")
					if not dry_run:
						s_path = path_join(source_dir, filename)
						d_path = path_join(dest_dir  , filename)
						copy_source_dest(s_path, d_path)
						utime_dest(d_path, (source_file.st_atime, source_file.st_mtime))
				elif source_file.st_mtime < dest_file.st_mtime:                             # Case 2
					if not silent: print(f"{cyan_d} -> {magenta_s}: {clr(filename, "green")}")
					if not dry_run:
						s_path = path_join(source_dir, filename)
						d_path = path_join(dest_dir  , filename)
						copy_dest_source(d_path, s_path)
						utime_source(s_path, (dest_file.st_atime, dest_file.st_mtime))
			elif source_file:
				if source_file.st_mtime >= newest_common_date:                              # Case 1
					if not silent: print(f"{magenta_s} -> {cyan_d}: {clr(filename, "green")}")
					if not dry_run:
						s_path = path_join(source_dir, filename)
						d_path = path_join(dest_dir  , filename)
						copy_source_dest(s_path, d_path)
						utime_dest(d_path, (source_file.st_atime, source_file.st_mtime))
				else:                                                                       # Case 3
					if not silent: print(f"{magenta_s}: {clr(filename, "red")}")
					if not dry_run:
						s_path = path_join(source_dir, filename)
						remove_source(s_path)
			elif dest_file:
				if dest_file.st_mtime >= newest_common_date:                                # Case 2
					if not silent: print(f"{cyan_d} -> {magenta_s}: {clr(filename, "green")}")
					if not dry_run:
						s_path = path_join(source_dir, filename)
						d_path = path_join(dest_dir  , filename)
						copy_dest_source(d_path, s_path)
						utime_source(s_path, (dest_file.st_atime, dest_file.st_mtime))
				else:                                                                       # Case 4
					if not silent: print(f"{cyan_d}: {clr(filename, "red")}")
					if not dry_run:
						d_path = path_join(dest_dir , filename)
						remove_dest(d_path)

			# # Alternative logic
			# if (source_file and dest_file and source_file.st_mtime > dest_file.st_mtime) or (source_file and not dest_file and source_file.st_mtime >= newest_common_date): # Case 1
			# 	if not silent: print(f"{magenta_s} -> {cyan_d}: {clr(filename, "green")}")
			# 	s_path = path_join(source_dir, filename)
			# 	d_path = path_join(dest_dir , filename)
			# 	copy_source_dest(s_path, d_path)
			# 	utime_dest(d_path, (source_file.st_atime, source_file.st_mtime))
			# elif (source_file and dest_file and source_file.st_mtime < dest_file.st_mtime) or (not source_file and dest_file and dest_file.st_mtime >= newest_common_date): # Case 2
			# 	if not silent: print(f"{cyan_d} -> {magenta_s}: {clr(filename, "green")}")
			# 	s_path = path_join(source_dir, filename)
			# 	d_path = path_join(dest_dir , filename)
			# 	copy_dest_source(d_path, s_path)
			# 	utime_source(s_path, (dest_file.st_atime, dest_file.st_mtime))
			# elif source_file and not dest_file and source_file.st_mtime < newest_common_date:                                                                      # Case 3
			# 	if not silent: print(f"{magenta_s}: {clr(filename, "yellow")}")
			# 	s_path = path_join(source_dir, filename)
			# 	remove_source(s_path)
			# elif not source_file and dest_file and dest_file.st_mtime < newest_common_date:                                                                        # Case 4
			# 	if not silent: print(f"{cyan_d}: {clr(filename, "yellow")}")
			# 	d_path = path_join(dest_dir , filename)
			# 	remove_dest(d_path)

		if source_place == Place.REMOTE and dest_place == Place.REMOTE and not dry_run:
			copy_source_dest.finalize()
			copy_dest_source.finalize()
			for path, times in utime_dest  .args: sftp.utime(path, times)
			for path, times in utime_source.args: sftp.utime(path, times)

	def copy_fun(source_files: list[Local_SFTPAttributes], source_place: Place, dest_files: dict[str, Local_SFTPAttributes], dest_place: Place, source_dir: str, dest_dir: str):
		if source_place == Place.LOCAL and dest_place == Place.LOCAL:
			copy = bindKwarg(shutil.copyfile, follow_symlinks=False)
			utime = os.utime
		elif source_place == Place.REMOTE and dest_place == Place.LOCAL:
			copy = sftp.get
			utime = os.utime
		elif source_place == Place.LOCAL and dest_place == Place.REMOTE:
			copy = bindKwarg(sftp.put, confirm=False)
			utime = sftp.utime
		elif source_place == Place.REMOTE and dest_place == Place.REMOTE:
			copy = Remote_copy_batch(source_dir, dest_dir, "cp -u", True)
			copy.files = map(getAttr("filename"), source_files)
			copy.finalize()
			return

		for file in source_files:
			dest_file = dest_files.get(file.filename)
			if dest_file and dest_file.st_mtime >= file.st_mtime: continue # destination exists and is newer or the same -> skip
			if not silent: cprint(file.filename, "green")
			if not dry_run:
				s_path = path_join(source_dir, file.filename)
				d_path = path_join(dest_dir  , file.filename)
				copy(s_path, d_path)
				utime(d_path, (file.st_atime, file.st_mtime))

	def del_copy_fun(source_files: list[Local_SFTPAttributes], source_place: Place, dest_files: dict[str, Local_SFTPAttributes], dest_place: Place, source_dir: str, dest_dir: str):
		if source_place == Place.LOCAL and dest_place == Place.LOCAL:
			copy = bindKwarg(shutil.copyfile, follow_symlinks=False)
			utime = os.utime
			remove_dest = os.remove
		elif source_place == Place.REMOTE and dest_place == Place.LOCAL:
			copy = sftp.get
			utime = os.utime
			remove_dest = os.remove
		elif source_place == Place.LOCAL and dest_place == Place.REMOTE:
			copy = bindKwarg(sftp.put, confirm=False)
			utime = sftp.utime
			remove_dest = sftp.remove
		elif source_place == Place.REMOTE and dest_place == Place.REMOTE: #TODO correct this part as it does not do proper DEL_COPY
			copy = Remote_copy_batch(source_dir, dest_dir, "cp -u", True)
			copy.files = map(getAttr("filename"), source_files)
			copy.finalize()
			return

		for file in source_files:
			dest_file = dest_files.pop(file.filename, None)
			if dest_file and dest_file.st_mtime >= file.st_mtime: continue # destination exists and is newer or the same -> skip
			if not silent: cprint(file.filename, "green")
			if not dry_run:
				s_path = path_join(source_dir, file.filename)
				d_path = path_join(dest_dir  , file.filename)
				copy(s_path, d_path)
				utime(d_path, (file.st_atime, file.st_mtime))

		for file in dest_files.values():
			if not silent: cprint(file.filename, "red")
			if not dry_run:
				d_path = path_join(dest_dir, file.filename)
				remove_dest(d_path)

	def move_fun(source_files: list[Local_SFTPAttributes], source_place: Place, dest_place: Place, source_dir: str, dest_dir: str):
		if source_place == Place.LOCAL and dest_place == Place.LOCAL:
			move = shutil.move
			def utime(x, y): pass
			def delete(x): pass
		elif source_place == Place.REMOTE and dest_place == Place.LOCAL:
			move = sftp.get
			utime = os.utime
			delete = sftp.remove
		elif source_place == Place.LOCAL and dest_place == Place.REMOTE:
			move = bindKwarg(sftp.put, confirm=False)
			utime = sftp.utime
			delete = os.remove
		elif source_place == Place.REMOTE and dest_place == Place.REMOTE:
			copy = Remote_copy_batch(source_dir, dest_dir, "mv", True)
			copy.files = map(getAttr("filename"), source_files)
			copy.finalize()
			return

		for file in source_files:
			if not silent: cprint(file.filename, "green")
			if not dry_run:
				s_path = path_join(source_dir, file.filename)
				d_path = path_join(dest_dir  , file.filename)
				move(s_path, d_path)
				utime(d_path, (file.st_atime, file.st_mtime))
				delete(s_path)

	# it's only noticeably faster if one of the remote folders that will be scanned has more than 5000 entries
	rld = Remote_list_dir(ssh, init=False, follow_symlinks=True) # don't init the remote python script because remote_listdir_attr might not get called at all
	remote_listdir_attr = rld.listdir_attr

	local_dir_list_cache = {}
	remote_dir_list_cache = {}
	for source_dir, source_place, dest_dir, dest_place, mode, file_patterns, default_match in parsed_operations:
		if source_place == Place.LOCAL:
			source_dir = normalize_local_folder_path(source_dir)
			assert_local_folder_exists(source_dir)
			source_dir_list_cache = local_dir_list_cache
		elif source_place == Place.REMOTE:
			source_dir = normalize_remote_folder_path(source_dir)
			assert_remote_folder_exists(sftp, source_dir)
			source_dir_list_cache = remote_dir_list_cache
		else:
			raise Simple_error(f"Invalid source_place: {source_place}")

		if dest_place == Place.LOCAL:
			dest_dir = normalize_local_folder_path(dest_dir)
			assert_local_folder_exists(dest_dir)
			dest_dir_list_cache = local_dir_list_cache
		elif dest_place == Place.REMOTE:
			dest_dir = normalize_remote_folder_path(dest_dir)
			assert_remote_folder_exists(sftp, dest_dir)
			dest_dir_list_cache = remote_dir_list_cache
		else:
			raise Simple_error(f"Invalid dest_place: {dest_place}")

		if not silent:
			print()
			print(f"# {magenta_source} ({clr(source_place._padded_name_, BLUE_COLOR)}): {source_dir}")
			print(f"# {cyan_dest   }   ({clr(dest_place  ._padded_name_, BLUE_COLOR)}): {dest_dir  }")
			print(f"# Mode: {clr(mode._padded_name_, BLUE_COLOR)}")
			print(f"# File patterns: {" ".join(clr(pattern, "green" if match_val else "red") for pattern, match_val in file_patterns)} | {clr("default_match", "green" if default_match else "red")}")

		source_files: list[Local_SFTPAttributes] = source_dir_list_cache.get(source_dir)
		if source_files is None:
			source_files = local_listdir_attr(source_dir) if source_place == Place.LOCAL else remote_listdir_attr(source_dir)
			if mode == Mode.SYNC:
				source_files = {file.filename: file for file in source_files if filter_fun(file, file_patterns, default_match)}
			else:
				source_files = tuple(file for file in source_files if filter_fun(file, file_patterns, default_match))
			if cache_directory_listings: source_dir_list_cache[source_dir] = source_files

		if not silent: print(f"# {magenta_source} file count: {len(source_files)}")

		if not source_files and mode != Mode.SYNC:
			continue

		if mode == Mode.SYNC and isinstance(source_files, tuple):
			source_files = {file.filename: file for file in source_files}
		elif mode != Mode.SYNC and isinstance(source_files, dict):
			source_files = source_files.values()

		if mode != Mode.MOVE:
			dest_files = dest_dir_list_cache.get(dest_dir)
			if dest_files is None:
				dest_files: list[Local_SFTPAttributes] = local_listdir_attr(dest_dir) if dest_place == Place.LOCAL else remote_listdir_attr(dest_dir)
				dest_files = {file.filename: file for file in dest_files if filter_fun(file, file_patterns, default_match)}
				if cache_directory_listings: dest_dir_list_cache[dest_dir] = dest_files

			if not silent: print(f"# {cyan_dest}   file count: {len(dest_files)}")

			if not source_files and not dest_files and mode == Mode.SYNC:
				continue

		match mode:
			case Mode.SYNC    : sync_fun    (source_files, source_place, dest_files, dest_place, source_dir, dest_dir)
			case Mode.COPY    : copy_fun    (source_files, source_place, dest_files, dest_place, source_dir, dest_dir)
			case Mode.DEL_COPY: del_copy_fun(source_files, source_place, dest_files, dest_place, source_dir, dest_dir)
			case Mode.MOVE    : move_fun    (source_files, source_place,             dest_place, source_dir, dest_dir)
			case _: raise Simple_error(f"Invalid mode: {mode}")

	sftp.close()
	ssh.close()

	if not silent: print(f"\nExecution time: {perf_counter() - start:.3f} s")

if __name__ == "__main__":
	main()
