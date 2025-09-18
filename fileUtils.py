import stat
import os
from datetime import datetime

def isFile(stats: os.stat_result):
	return stat.S_ISREG(stats.st_mode)

def isDir(stats: os.stat_result):
	return stat.S_ISDIR(stats.st_mode)

def modifiedDate(stats: os.stat_result):
	return datetime.fromtimestamp(stats.st_mtime)

def accessedDate(stats: os.stat_result):
	return datetime.fromtimestamp(stats.st_atime)
