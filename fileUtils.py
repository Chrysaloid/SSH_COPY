from pathlib import Path; __package__ = Path(__file__).resolve().parent.name # To be able to use relative imports

from datetime import datetime
import os
from stat import S_ISDIR, S_ISREG

from .SimpleError import SimpleError

def isFile(stats: os.stat_result):
	return S_ISREG(stats.st_mode)

def isDir(stats: os.stat_result):
	return S_ISDIR(stats.st_mode)

def modifiedDate(stats: os.stat_result):
	return datetime.fromtimestamp(stats.st_mtime)

def accessedDate(stats: os.stat_result):
	return datetime.fromtimestamp(stats.st_atime)

def mkdir(path: str):
	""" Returns True if folder was created and False if it already exists """
	try:
		os.mkdir(path)
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
	if not os.path.isdir(path):
		raise SimpleError(f'The local folder "{path}" does not exist or is not a folder{additionalComment}')

def ensureFolderExists(path: str):
	os.makedirs(path, exist_ok=True)

class LocalDirEntry:
	def __init__(self, absPath: str):
		self.path = absPath # os.path.abspath(absPath)
		self.name = os.path.basename(absPath)

	def stat(self, follow_symlinks=True):
		return os.stat(self.path, follow_symlinks=follow_symlinks)
