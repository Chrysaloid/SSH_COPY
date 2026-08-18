from pathlib import Path as _Path; __package__ = _Path(__file__).resolve().parent.name # To be able to use relative imports

from datetime import datetime as _datetime
import glob as _glob
import os as _os
import re as _re
from stat import S_ISDIR as _S_ISDIR, S_ISREG as _S_ISREG

from .SimpleError import SimpleError as _SimpleError

WINDOWS_RESERVED_NAMES = set("con, prn, aux, nul, com1, com2, com3, com4, com5, com6, com7, com8, com9, com¹, com², com³, lpt1, lpt2, lpt3, lpt4, lpt5, lpt6, lpt7, lpt8, lpt9, lpt¹, lpt², lpt³".split(", "))
INVALID_FILENAME_CHARS = _re.compile(r'[<>:"/\|?*\x00-\x1F]')
FILENAME_EXT_SPLIT = _re.compile(r"^(.*?)(\.\w*?)$")

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

def iteratePathParts(path: str):
	path = path.replace("\\", "/").rstrip("/") # TODO: Enhance path normalization and sanitization
	idx = path.index("/")
	start = idx + 1
	while True:
		try:
			idx = path.index("/", start)
			start = idx + 1
			yield path[:idx]
		except:
			break

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

def readTextFile(path: str | _Path, encoding="UTF-8"):
	with open(path, "rt", encoding=encoding) as f:
		return f.read()

def readSplitLines(path: str | _Path, encoding="UTF-8"):
	with open(path, "rt", encoding=encoding) as f:
		return f.read().splitlines()

def readLines(path: str | _Path, encoding="UTF-8"):
	with open(path, "rt", encoding=encoding) as f:
		for line in f:
			line = line.rstrip()
			if line:
				yield line

def writeTextFile(path: str | _Path, text: str, append=False, encoding="UTF-8"):
	with open(path, "at" if append else "wt", encoding=encoding) as f:
		return f.write(text)

def writeLines(path: str | _Path, lines: list[str], append=False, encoding="UTF-8"):
	with open(path, "at" if append else "wt", encoding=encoding) as f:
		return f.write("\n".join(lines)) + f.write("\n")

def globOneFile(globPattern: str):
	return next(_glob.iglob(globPattern), None).replace("\\","/")

class LocalDirEntry:
	def __init__(self, absPath: str):
		self.path = absPath # os.path.abspath(absPath)
		self.name = _os.path.basename(absPath)

	def stat(self, follow_symlinks=True):
		return _os.stat(self.path, follow_symlinks=follow_symlinks)

if __name__ == "__main__": # Example usage
	from os.path import isdir as isDir, isfile as isFile # use this instead of my _isPath*

	from myLibs.fileUtils import _isPathDir, _isPathFile, createSymlink, readLines, readSplitLines, readTextFile

	print(_isPathFile(__file__), isFile(__file__))
	print(_isPathDir(__file__), isDir(__file__))

	testFile = "G:/Biblioteki Windows/Dokumenty/1. Mój Folder/Informatyka/Python/myLibs/my lines.txt"

	print(readTextFile(testFile))
	print(tuple(readLines(testFile)))
	print(readSplitLines(testFile))
