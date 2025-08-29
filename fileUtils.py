import stat
import os
from datetime import datetime
import paramiko
from SimpleError import SimpleError

def isFile(stats: os.stat_result):
	return stat.S_ISREG(stats.st_mode)

def isDir(stats: os.stat_result):
	return stat.S_ISDIR(stats.st_mode)

def modifiedDate(stats: os.stat_result):
	return datetime.fromtimestamp(stats.st_mtime)

def accessedDate(stats: os.stat_result):
	return datetime.fromtimestamp(stats.st_atime)

def remoteFolderExists(sftp: paramiko.SFTPClient, remotePath: str) -> bool:
	try:
		fileInfo = sftp.stat(remotePath) # Raises FileNotFoundError if it doesn't exist
		return isDir(fileInfo)
	except FileNotFoundError:
		return False

def assertRemoteFolderExists(sftp: paramiko.SFTPClient, remotePath: str):
	if not remoteFolderExists(sftp, remotePath):
		raise SimpleError(f'The remote folder "{remotePath}" does not exist or is not a folder')
