from termcolor import colored as clr
import os
import paramiko
import argparse
import time
from fnmatch import fnmatchcase
import sys
from datetime import datetime
import posixpath

start = time.time()

from SimpleError import SimpleError
from getSSH import getSSH
from getPlatform import WINDOWS
from fileUtils import isFile, isDir, assertRemoteFolderExists, modifiedDate

TITLE = "SSH SYNC"

if WINDOWS:
	import ctypes
	ctypes.windll.kernel32.SetConsoleTitleW(TITLE) # Hide title from shortcut
	os.system("color")
else:
	print(f"\33]0;{TITLE}\a", end="", flush=True) # Hide title

parser = argparse.ArgumentParser(description="Parse connection details")

parser.add_argument("-u", "--username"     , required=True, help="Remote username")
parser.add_argument("-H", "--hostname"     , required=True, help="Remote host's address")
parser.add_argument("-p", "--password"     , required=True, help="Remote password")
parser.add_argument("-l", "--local-folder" , required=True, help="Local folder's absolute path", dest="localFolder")
parser.add_argument("-r", "--remote-folder", required=True, help="Remote folder's absolute path", dest="remoteFolder")

parser.add_argument("-i", "--include"       , default=[], action="append", help="Glob pattern for filenames to include")
parser.add_argument("-e", "--exclude"       , default=[], action="append", help="Glob pattern for filenames to exclude")
parser.add_argument("-n", "--newer-than"    , default="", help="Copy only files newer then", dest="newerThan")
parser.add_argument("-P", "--port"          , default=22, type=int, help="Remote port (default: 22)")
parser.add_argument("-T", "--timeout"       , default=1, type=float, help="TCP 3-way handshake timeout in seconds (default: 1)")
parser.add_argument("-t", "--preserve-times", action="store_true" , help="If set, modification times will be preserved", dest="preserveTimes")
parser.add_argument("-d", "--dont-close"    , action="store_true" , help="Don't auto-close console window at the end if no error occurred. You will have to close it manually or by pressing ENTER", dest="dontClose")

args = parser.parse_args()

username      : str       = args.username
hostname      : str       = args.hostname
password      : str       = args.password
localFolder   : str       = args.localFolder
remoteFolder  : str       = args.remoteFolder
include       : list[str] = args.include
exclude       : list[str] = args.exclude
newerThan     : str       = args.newerThan
port          : int       = args.port
timeout       : float     = args.timeout
preserveTimes : bool      = args.preserveTimes
dontClose     : bool      = args.dontClose

if not os.path.isdir(localFolder):
	raise SimpleError(f'Folder "{localFolder}" does not exist')
else:
	localFolder = localFolder.replace("\\", "/")

newerThanDate = None
if newerThan:
	for format in [
		"%Y",
		"%Y-%m",
		"%Y-%m-%d",
		"%Y-%m-%d %H",
		"%Y-%m-%d %H:%M",
		"%Y-%m-%d %H:%M:%S",
	]:
		try:
			newerThanDate = datetime.strptime(newerThan, format)
			break
		except ValueError:
			pass
	if not newerThanDate:
		raise SimpleError(f'Incorrect -n/--newer-than parameter: {newerThan}')

defaultFileMatch = True
# fileMatchReasonable = include or exclude
if include and exclude:
	iIdx1 = iIdx2 = eIdx1 = eIdx2 = 10**10
	try:
		iIdx1 = sys.argv.index("-i")
	except ValueError: pass
	try:
		iIdx2 = sys.argv.index("--include")
	except ValueError: pass
	includePos = min(iIdx1, iIdx2)

	try:
		eIdx1 = sys.argv.index("-e")
	except ValueError: pass
	try:
		eIdx2 = sys.argv.index("--exclude")
	except ValueError: pass
	excludePos = min(eIdx1, eIdx2)

	# if exclude was first - match everything by default, if include was first - match nothing by default
	defaultFileMatch = excludePos < includePos

def fileMatch(filename: str):
	for pattern in include:
		if fnmatchcase(filename, pattern):
			return True

	for pattern in exclude:
		if fnmatchcase(filename, pattern):
			return False

	return defaultFileMatch

ssh = getSSH(username, hostname, password, timeout, port)
sftp = ssh.open_sftp()

try:
	assertRemoteFolderExists(sftp, remoteFolder)
	remoteFolder = remoteFolder.replace("\\", "/")

	def recursive_copy(remoteFolderParam: str, localFolderParam: str):
		for fileInfo in sftp.listdir_attr(remoteFolderParam):
			filename = fileInfo.filename
			if fileMatch(filename) and (newerThanDate is None or newerThanDate <= modifiedDate(fileInfo)):
				if isDir(fileInfo):
					newLocalFolder = posixpath.join(localFolderParam, filename)
					os.makedirs(newLocalFolder, exist_ok=True)
					newRemoteFolder = posixpath.join(remoteFolderParam, filename)
					recursive_copy(newRemoteFolder, newLocalFolder)
				elif isFile(fileInfo):
					locPath = posixpath.join(localFolderParam, filename)
					remPath = posixpath.join(remoteFolderParam, filename)
					# if not os.path.exists(locPath) or modifiedDate(os.stat(locPath)) < modifiedDate(fileInfo):
					if not os.path.exists(locPath):
						print(os.path.relpath(remPath, remoteFolder))
						sftp.get(remPath, locPath)
						if preserveTimes:
							os.utime(locPath, (fileInfo.st_atime, fileInfo.st_mtime))
					# else:
					# 	print(os.path.relpath(remPath, remoteFolder), "exists. Skipping...")

	print(f"Local folder: {localFolder}")
	print(f"Remote folder: {remoteFolder}")
	print("Copying files:\n")

	recursive_copy(remoteFolder, localFolder)

	print(f"\nExecution time: {time.time() - start:.3f} s")

	if dontClose:
		input(clr("\nPress ENTER to continue...", "green"))
except SimpleError as e:
	raise e
finally:
	sftp.close()
	ssh.close()
