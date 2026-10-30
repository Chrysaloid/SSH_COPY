from pathlib import Path as _Path; __package__ = __package__ or _Path(__file__).resolve().parent.name # To be able to use relative imports when run directly - never override a __package__ Python already set (see README)

from datetime import datetime as _datetime
from enum import auto, IntEnum
import glob as _glob
import os as _os
import re as _re
import shutil as _shutil
from stat import S_ISDIR as _S_ISDIR, S_ISLNK as _S_ISLNK, S_ISREG as _S_ISREG, S_ISVTX as _S_ISVTX
import sys as _sys
from typing import Callable
from urllib.parse import quote as _quote

from .list_get import list_get
from .simple_error import Simple_error as _Simple_error

WINDOWS_RESERVED_NAMES = set("con, prn, aux, nul, com1, com2, com3, com4, com5, com6, com7, com8, com9, com¹, com², com³, lpt1, lpt2, lpt3, lpt4, lpt5, lpt6, lpt7, lpt8, lpt9, lpt¹, lpt², lpt³".split(", "))
INVALID_FILENAME_CHARS = _re.compile(r'[<>:"/\\|?*\x00-\x1F]')
FILENAME_EXT_SPLIT = _re.compile(r"^(.*?)(\.\w*?)$")

def read(path: str | _Path, encoding="UTF-8", newline="\n"):
	""" Read file as UTF-8 text """
	return open(path, "rt", encoding=encoding, newline=newline)

def write(path: str | _Path, encoding="UTF-8", newline="\n"):
	""" Write file as UTF-8 text """
	return open(path, "wt", encoding=encoding, newline=newline)

def append(path: str | _Path, encoding="UTF-8", newline="\n"):
	""" Append UTF-8 text to file """
	return open(path, "at", encoding=encoding, newline=newline)

def read_binary(path: str | _Path):
	""" Read file as bytes """
	return open(path, "rb")

def write_binary(path: str | _Path):
	""" Write file as bytes """
	return open(path, "wb")

def append_binary(path: str | _Path):
	""" Append bytes to file """
	return open(path, "ab")

IS_WINDOWS = _sys.platform == "win32"

if IS_WINDOWS:
	import ctypes as _ctypes
	import ctypes.wintypes as _wt

	class _ShFileOpStructW(_ctypes.Structure):
		_fields_ = [
			("hwnd"                  , _wt.HWND),
			("wFunc"                 , _wt.UINT),
			("pFrom"                 , _wt.LPCWSTR),
			("pTo"                   , _wt.LPCWSTR),
			("fFlags"                , _ctypes.c_uint),
			("fAnyOperationsAborted" , _wt.BOOL),
			("hNameMappings"         , _ctypes.c_uint),
			("lpszProgressTitle"     , _wt.LPCWSTR),
		]

	def _recycle_windows(path: str) -> None:
		op = _ShFileOpStructW(
			hwnd   = None,
			wFunc  = 3, # FO_DELETE
			pFrom  = path + "\0\0",
			pTo    = None,
			fFlags = 0x0040 | 0x0010 | 0x0004 | 0x0400, # ALLOWUNDO | NOCONFIRMATION | SILENT | NOERRORUI
		)
		res = _ctypes.windll.shell32.SHFileOperationW(_ctypes.byref(op))
		if res != 0 or op.fAnyOperationsAborted:
			raise OSError(f"SHFileOperationW failed on {path}: code {res}, aborted {op.fAnyOperationsAborted}")

def _mount_point_of(path: str):
	""" Topmost directory of the filesystem `path` lives on (`path` must exist) """
	dev = _os.lstat(path).st_dev
	while True:
		parent = _os.path.dirname(path)
		if parent == path or _os.lstat(parent).st_dev != dev:
			return path
		path = parent

def _volume_trash_dir(top_dir: str):
	"""
	Trash directory of a non-home volume, per the freedesktop.org trash spec:
	`$topdir/.Trash/$uid` when an admin-created sticky, non-symlink `$topdir/.Trash` exists,
	otherwise our own `$topdir/.Trash-$uid`
	"""
	uid = _os.getuid()
	admin_trash = _os.path.join(top_dir, ".Trash")
	if not _os.path.islink(admin_trash) and _os.path.isdir(admin_trash) and (_os.stat(admin_trash).st_mode & _S_ISVTX):
		return _os.path.join(admin_trash, str(uid))
	return _os.path.join(top_dir, f".Trash-{uid}")

def _recycle_xdg_trash(path: str) -> None:
	home_trash = _os.path.join(_os.environ.get("XDG_DATA_HOME") or _os.path.expanduser("~/.local/share"), "Trash")
	ensure_folder_exists(home_trash)
	trash_dir = home_trash
	relative_to = ""
	if _os.lstat(path).st_dev != _os.lstat(home_trash).st_dev: # A trash can must live on the same filesystem as the file - moving across one would be a copy + permanent delete
		relative_to = _mount_point_of(path)
		trash_dir = _volume_trash_dir(relative_to)
		try:
			ensure_folder_exists(trash_dir)
		except OSError as e:
			raise _Simple_error(f'"{path}" is on the volume "{relative_to}", which has no usable trash can ({e}) - refusing to delete it permanently') from e

	files_dir = _os.path.join(trash_dir, "files")
	info_dir = _os.path.join(trash_dir, "info")
	ensure_folder_exists(files_dir)
	ensure_folder_exists(info_dir)

	name = _os.path.basename(path.rstrip("/"))
	base, ext = _os.path.splitext(name)
	trash_name = name
	for i in range(1, 10000): # The name must be unique inside the trash can - keep the extension so the file stays recognizable
		info_path = _os.path.join(info_dir, trash_name + ".trashinfo")
		try:
			fd = _os.open(info_path, _os.O_CREAT | _os.O_EXCL | _os.O_WRONLY, 0o600) # Creating the .trashinfo file exclusively is what reserves the name
			break
		except FileExistsError:
			trash_name = f"{base}_{i}{ext}"
	else:
		raise _Simple_error(f'Could not find a free name for "{path}" in the trash can "{trash_dir}"')

	orig_path = path if not relative_to else _os.path.relpath(path, relative_to)
	with _os.fdopen(fd, "wt", encoding="UTF-8") as f:
		f.write(f"[Trash Info]\nPath={_quote(orig_path)}\nDeletionDate={_datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}\n")

	try:
		_shutil.move(path, _os.path.join(files_dir, trash_name)) # Same filesystem, so this is a plain rename
	except BaseException:
		_os.remove(info_path)
		raise

def recycle(path: str | _Path) -> None:
	""" Sends `path` to the Recycle Bin / trash can (never a permanent delete) """
	path = _os.path.abspath(str(path))
	if IS_WINDOWS:
		_recycle_windows(path)
	else:
		_recycle_xdg_trash(path)
	if _os.path.lexists(path):
		raise OSError(f"{path} still exists after the recycle attempt")

def sanitize_filename(name: str, sub_char = "_"):
	r""" `sub_char`: substitute character for invalid charactes """
	name = name.strip().rstrip(".")

	# Split extension safely
	m_obj = FILENAME_EXT_SPLIT.match(name)
	if m_obj:
		base = m_obj[1]
		ext = m_obj[2]
	else:
		base = name
		ext = ""

	# Replace invalid characters
	base = INVALID_FILENAME_CHARS.sub(sub_char, base)

	# Remove trailing dots/spaces (Windows rule)
	base = base.rstrip(". ")

	# Handle empty base
	if not base:
		base = "file"

	# Handle Windows reserved names (case-insensitive)
	if base.lower() in WINDOWS_RESERVED_NAMES:
		base = f"{base}_"

	return base + ext

def is_file(stats: _os.stat_result):
	return _S_ISREG(stats.st_mode)

def is_symlink(stats: _os.stat_result):
	return _S_ISLNK(stats.st_mode)

def is_file_or_symlink(stats: _os.stat_result):
	return _S_ISREG(stats.st_mode) or _S_ISLNK(stats.st_mode)

def is_dir(stats: _os.stat_result):
	return _S_ISDIR(stats.st_mode)

def safe_stat(path: str) -> _os.stat_result | None:
	try:
		return _os.stat(path)
	except FileNotFoundError:
		return None

def _is_path_file(path: str): # see examples
	return _S_ISREG(_os.stat(path).st_mode)

def _is_path_dir(path: str): # see examples
	return _S_ISDIR(_os.stat(path).st_mode)

def modified_date(stats: _os.stat_result):
	return _datetime.fromtimestamp(stats.st_mtime)

def accessed_date(stats: _os.stat_result):
	return _datetime.fromtimestamp(stats.st_atime)

def mkdir(path: str):
	""" Returns True if folder was created and False if it already exists """
	try:
		_os.mkdir(path)
		return True
	except FileExistsError:
		return False

def iterate_path_parts(path: str, skip_root = True):
	path = path.replace("\\", "/").rstrip("/") # TODO: Enhance path normalization and sanitization
	start = path.find("/")
	if start < 0:
		return path
	start = start + (1 if skip_root else 0)
	while True:
		idx = path.find("/", start)
		if idx < 0:
			break
		start = idx + 1
		yield path[:start]
	yield path

def assert_folder_exists(path: str, additional_comment = ""):
	if not _os.path.isdir(path):
		raise _Simple_error(f'The local folder "{path}" does not exist or is not a folder{additional_comment}')

def ensure_folder_exists(path: str):
	_os.makedirs(path, exist_ok=True)

class Action(IntEnum):
	NOTHING = auto()
	WARN    = auto()
	ERROR   = auto()

def ensure_folder_is_deleted(path: str | _Path, not_folder_action = Action.WARN, warn_comment = " - skipping"):
	folder = _Path(path).resolve()

	if not folder.exists():
		return True

	if not folder.is_dir(follow_symlinks = False):
		match not_folder_action:
			case Action.NOTHING:
				return False
			case Action.WARN:
				_cprint(f'"{path}" is not a folder{warn_comment}', _COLOR_WARN)
				return False
			case Action.ERROR:
				raise _Simple_error(f'"{path}" is not a folder')
			case _:
				raise _Simple_error(f"Invalid not_folder_action: {not_folder_action}")

	_shutil.rmtree(folder)
	return True

def iter_scan_dir(path: str):
	"""
	Usage:
	```
	for entry in iter_scan_dir("/some/path"):
		print(entry)
	```
	"""
	with _os.scandir(path) as it:
		for entry in it:
			yield entry

def create_symlink(link_name, target):
	"""
	Create or overwrite a symbolic link

	:param link_name: Path where the symlink should be created
	:param target: Path to the real file or directory
	"""

	# Normalize paths
	target = _os.path.abspath(target)
	link_name = _os.path.abspath(link_name)

	if _os.path.lexists(link_name): # Remove existing file/symlink
		_os.remove(link_name)

	_os.symlink(target, link_name, target_is_directory=_os.path.isdir(target))

def read_text_file(path: str | _Path, encoding="UTF-8", newline=None):
	with open(path, "rt", encoding=encoding, newline=newline) as f:
		return f.read()

def read_lines(path: str | _Path, keep_empty_lines=False, keep_line_endings=False, encoding="UTF-8"):
	with open(path, "rt", encoding=encoding) as f:
		if keep_empty_lines:
			if keep_line_endings:
				for line in f:
					yield line
			else:
				for line in f:
					yield line.rstrip()
		else:
			if keep_line_endings: # this is probably useless
				for line in f:
					if line:
						yield line
			else: # default
				for line in f:
					line = line.rstrip()
					if line:
						yield line

def write_text_file(path: str | _Path, text: str, append=False, encoding="UTF-8", newline=None):
	with open(path, "at" if append else "wt", encoding=encoding, newline=newline) as f:
		return f.write(text)

def write_lines(path: str | _Path, lines: list[str], append=False, encoding="UTF-8"):
	with open(path, "at" if append else "wt", encoding=encoding) as f:
		return f.write("\n".join(lines)) + f.write("\n")

def glob_one_file(
	glob_path_pattern: str,
	name_sort_key: Callable = None,
	name_sort_reverse: bool = None,
	recursive = False,
	include_hidden = False,
) -> str:
	name_iter = _glob.iglob(str(glob_path_pattern), recursive=recursive, include_hidden=include_hidden)
	if name_sort_key or name_sort_reverse is not None:
		the_one = list_get(sorted(name_iter, key=name_sort_key, reverse=name_sort_reverse), 0, "")
	else:
		the_one = next(name_iter, "")
	return the_one.replace("\\","/")

class Local_DirEntry:
	def __init__(self, abs_path: str):
		self.path = abs_path # os.path.abspath(abs_path)
		self.name = _os.path.basename(abs_path)

	def stat(self, follow_symlinks=True):
		return _os.stat(self.path, follow_symlinks=follow_symlinks)

if __name__ == "__main__": # Example usage
	from os.path import isdir as is_dir, isfile as is_file # use this instead of my _isPath*

	from my_libs.file_utils import _is_path_dir, _is_path_file, create_symlink, read_lines, read_text_file

	print(_is_path_file(__file__), is_file(__file__))
	print(_is_path_dir(__file__), is_dir(__file__))

	test_file = "G:/Biblioteki Windows/Dokumenty/1. Mój Folder/Informatyka/Python/my_libs/my lines.txt"

	print(read_text_file(test_file))
	print(tuple(read_lines(test_file)))
	print(read_text_file(test_file).split())
	print()

	print(list(iterate_path_parts("C:/abc"    )))
	print(list(iterate_path_parts("C:/abc/def")))
	print(list(iterate_path_parts("/abc"      )))
	print(list(iterate_path_parts("/abc/def"  )))
	print()
	print(list(iterate_path_parts("C:/abc"    , 0)))
	print(list(iterate_path_parts("C:/abc/def", 0)))
	print(list(iterate_path_parts("/abc"      , 0)))
	print(list(iterate_path_parts("/abc/def"  , 0)))
