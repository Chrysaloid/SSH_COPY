from pathlib import Path as _Path; __package__ = __package__ or _Path(__file__).resolve().parent.name # To be able to use relative imports when run directly - never override a __package__ Python already set (see README)

from datetime import datetime as _datetime
import glob as _glob
import os as _os
import re as _re
import shutil as _shutil
from stat import S_ISDIR as _S_ISDIR, S_ISLNK as _S_ISLNK, S_ISREG as _S_ISREG, S_ISVTX as _S_ISVTX
import sys as _sys
from urllib.parse import quote as _quote

from .SimpleError import SimpleError as _SimpleError

WINDOWS_RESERVED_NAMES = set("con, prn, aux, nul, com1, com2, com3, com4, com5, com6, com7, com8, com9, com¹, com², com³, lpt1, lpt2, lpt3, lpt4, lpt5, lpt6, lpt7, lpt8, lpt9, lpt¹, lpt², lpt³".split(", "))
INVALID_FILENAME_CHARS = _re.compile(r'[<>:"/\|?*\x00-\x1F]')
FILENAME_EXT_SPLIT = _re.compile(r"^(.*?)(\.\w*?)$")

def read(path: str | _Path, encoding="UTF-8"):
	""" Read file as UTF-8 text """
	return open(path, "rt", encoding=encoding)

def write(path: str | _Path, encoding="UTF-8"):
	""" Write file as UTF-8 text """
	return open(path, "wt", encoding=encoding)

def append(path: str | _Path, encoding="UTF-8"):
	""" Append UTF-8 text to file """
	return open(path, "at", encoding=encoding)

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

	def _recycleWindows(path: str) -> None:
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

def _mountPointOf(path: str):
	""" Topmost directory of the filesystem `path` lives on (`path` must exist) """
	dev = _os.lstat(path).st_dev
	while True:
		parent = _os.path.dirname(path)
		if parent == path or _os.lstat(parent).st_dev != dev:
			return path
		path = parent

def _volumeTrashDir(topDir: str):
	"""
	Trash directory of a non-home volume, per the freedesktop.org trash spec:
	`$topdir/.Trash/$uid` when an admin-created sticky, non-symlink `$topdir/.Trash` exists,
	otherwise our own `$topdir/.Trash-$uid`
	"""
	uid = _os.getuid()
	adminTrash = _os.path.join(topDir, ".Trash")
	if not _os.path.islink(adminTrash) and _os.path.isdir(adminTrash) and (_os.stat(adminTrash).st_mode & _S_ISVTX):
		return _os.path.join(adminTrash, str(uid))
	return _os.path.join(topDir, f".Trash-{uid}")

def _recycleXdgTrash(path: str) -> None:
	homeTrash = _os.path.join(_os.environ.get("XDG_DATA_HOME") or _os.path.expanduser("~/.local/share"), "Trash")
	ensureFolderExists(homeTrash)
	trashDir = homeTrash
	relativeTo = ""
	if _os.lstat(path).st_dev != _os.lstat(homeTrash).st_dev: # A trash can must live on the same filesystem as the file - moving across one would be a copy + permanent delete
		relativeTo = _mountPointOf(path)
		trashDir = _volumeTrashDir(relativeTo)
		try:
			ensureFolderExists(trashDir)
		except OSError as e:
			raise _SimpleError(f'"{path}" is on the volume "{relativeTo}", which has no usable trash can ({e}) - refusing to delete it permanently') from e

	filesDir = _os.path.join(trashDir, "files")
	infoDir = _os.path.join(trashDir, "info")
	ensureFolderExists(filesDir)
	ensureFolderExists(infoDir)

	name = _os.path.basename(path.rstrip("/"))
	base, ext = _os.path.splitext(name)
	trashName = name
	for i in range(1, 10000): # The name must be unique inside the trash can - keep the extension so the file stays recognizable
		infoPath = _os.path.join(infoDir, trashName + ".trashinfo")
		try:
			fd = _os.open(infoPath, _os.O_CREAT | _os.O_EXCL | _os.O_WRONLY, 0o600) # Creating the .trashinfo file exclusively is what reserves the name
			break
		except FileExistsError:
			trashName = f"{base}_{i}{ext}"
	else:
		raise _SimpleError(f'Could not find a free name for "{path}" in the trash can "{trashDir}"')

	origPath = path if not relativeTo else _os.path.relpath(path, relativeTo)
	with _os.fdopen(fd, "wt", encoding="UTF-8") as f:
		f.write(f"[Trash Info]\nPath={_quote(origPath)}\nDeletionDate={_datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}\n")

	try:
		_shutil.move(path, _os.path.join(filesDir, trashName)) # Same filesystem, so this is a plain rename
	except BaseException:
		_os.remove(infoPath)
		raise

def recycle(path: str | _Path) -> None:
	""" Sends `path` to the Recycle Bin / trash can (never a permanent delete) """
	path = _os.path.abspath(str(path))
	if IS_WINDOWS:
		_recycleWindows(path)
	else:
		_recycleXdgTrash(path)
	if _os.path.lexists(path):
		raise OSError(f"{path} still exists after the recycle attempt")

def sanitizeFilename(name: str):
	name = name.strip().rstrip(".")

	# Split extension safely
	mObj = FILENAME_EXT_SPLIT.match(name)
	if mObj:
		base = mObj[1]
		ext = mObj[2]
	else:
		base = name
		ext = ""

	# Replace invalid characters
	base = INVALID_FILENAME_CHARS.sub("_", base)

	# Remove trailing dots/spaces (Windows rule)
	base = base.rstrip(". ")

	# Handle empty base
	if not base:
		base = "file"

	# Handle Windows reserved names (case-insensitive)
	if base.lower() in WINDOWS_RESERVED_NAMES:
		base = f"{base}_"

	return base + ext

def isFile(stats: _os.stat_result):
	return _S_ISREG(stats.st_mode)

def isSymlink(stats: _os.stat_result):
	return _S_ISLNK(stats.st_mode)

def isFileOrSymlink(stats: _os.stat_result):
	return _S_ISREG(stats.st_mode) or _S_ISLNK(stats.st_mode)

def isDir(stats: _os.stat_result):
	return _S_ISDIR(stats.st_mode)

def safeStat(path: str) -> _os.stat_result | None:
	try:
		return _os.stat(path)
	except FileNotFoundError:
		return None

def _isPathFile(path: str): # see examples
	return _S_ISREG(_os.stat(path).st_mode)

def _isPathDir(path: str): # see examples
	return _S_ISDIR(_os.stat(path).st_mode)

def modifiedDate(stats: _os.stat_result):
	return _datetime.fromtimestamp(stats.st_mtime)

def accessedDate(stats: _os.stat_result):
	return _datetime.fromtimestamp(stats.st_atime)

def mkdir(path: str):
	""" Returns True if folder was created and False if it already exists """
	try:
		_os.mkdir(path)
		return True
	except FileExistsError:
		return False

def iteratePathParts(path: str, skipRoot = True):
	path = path.replace("\\", "/").rstrip("/") # TODO: Enhance path normalization and sanitization
	start = path.find("/")
	if start < 0:
		return path
	start = start + (1 if skipRoot else 0)
	while True:
		idx = path.find("/", start)
		if idx < 0:
			break
		start = idx + 1
		yield path[:start]
	yield path

def assertFolderExists(path: str, additionalComment = ""):
	if not _os.path.isdir(path):
		raise _SimpleError(f'The local folder "{path}" does not exist or is not a folder{additionalComment}')

def ensureFolderExists(path: str):
	_os.makedirs(path, exist_ok=True)

def iterScanDir(path: str):
	"""
	Usage:
	```
	for entry in iterScanDir("/some/path"):
		print(entry)
	```
	"""
	with _os.scandir(path) as it:
		for entry in it:
			yield entry

def createSymlink(linkName, target):
	"""
	Create or overwrite a symbolic link

	:param linkName: Path where the symlink should be created
	:param target: Path to the real file or directory
	"""

	# Normalize paths
	target = _os.path.abspath(target)
	linkName = _os.path.abspath(linkName)

	if _os.path.lexists(linkName): # Remove existing file/symlink
		_os.remove(linkName)

	_os.symlink(target, linkName, target_is_directory=_os.path.isdir(target))

def readTextFile(path: str | _Path, encoding="UTF-8", newline=None):
	with open(path, "rt", encoding=encoding, newline=newline) as f:
		return f.read()

def readLines(path: str | _Path, keep_empty_lines=False, keep_line_endings=False, encoding="UTF-8"):
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

def writeTextFile(path: str | _Path, text: str, append=False, encoding="UTF-8", newline=None):
	with open(path, "at" if append else "wt", encoding=encoding, newline=newline) as f:
		return f.write(text)

def writeLines(path: str | _Path, lines: list[str], append=False, encoding="UTF-8"):
	with open(path, "at" if append else "wt", encoding=encoding) as f:
		return f.write("\n".join(lines)) + f.write("\n")

def globOneFile(globPattern: str):
	return next(_glob.iglob(str(globPattern)), None).replace("\\","/")

class LocalDirEntry:
	def __init__(self, absPath: str):
		self.path = absPath # os.path.abspath(absPath)
		self.name = _os.path.basename(absPath)

	def stat(self, follow_symlinks=True):
		return _os.stat(self.path, follow_symlinks=follow_symlinks)

if __name__ == "__main__": # Example usage
	from os.path import isdir as isDir, isfile as isFile # use this instead of my _isPath*

	from myLibs.fileUtils import _isPathDir, _isPathFile, createSymlink, readLines, readTextFile

	print(_isPathFile(__file__), isFile(__file__))
	print(_isPathDir(__file__), isDir(__file__))

	testFile = "G:/Biblioteki Windows/Dokumenty/1. Mój Folder/Informatyka/Python/myLibs/my lines.txt"

	print(readTextFile(testFile))
	print(tuple(readLines(testFile)))
	print(readTextFile(testFile).split())
	print()

	print(list(iteratePathParts("C:/abc"    )))
	print(list(iteratePathParts("C:/abc/def")))
	print(list(iteratePathParts("/abc"      )))
	print(list(iteratePathParts("/abc/def"  )))
	print()
	print(list(iteratePathParts("C:/abc"    , 0)))
	print(list(iteratePathParts("C:/abc/def", 0)))
	print(list(iteratePathParts("/abc"      , 0)))
	print(list(iteratePathParts("/abc/def"  , 0)))
