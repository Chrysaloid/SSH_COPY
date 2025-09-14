# Version: 1.1.0

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
from fileUtils import isFile, isDir, assertRemoteFolderExists

TITLE = "SSH SYNC"

if WINDOWS:
	import ctypes
	ctypes.windll.kernel32.SetConsoleTitleW(TITLE) # Hide title from shortcut
	os.system("color")
else:
	print(f"\33]0;{TITLE}\a", end="", flush=True) # Hide title

parser = argparse.ArgumentParser(description="Parse sync details")

parser.add_argument("-u", "--username"     , required=True, help="Remote username")
parser.add_argument("-H", "--hostname"     , required=True, help="Remote host's address")
parser.add_argument("-p", "--password"     , required=True, help="Remote password")
parser.add_argument("-l", "--local-folder" , required=True, help="Local folder's absolute path", dest="localFolder")
parser.add_argument("-r", "--remote-folder", required=True, help="Remote folder's absolute path", dest="remoteFolder")

parser.add_argument("-i", "--include-files"     , default=[], action="append", help="Glob pattern for files to include", dest="includeFiles")
parser.add_argument("-e", "--exclude-files"     , default=[], action="append", help="Glob pattern for files to exclude", dest="excludeFiles")
parser.add_argument("-I", "--include-folders"   , default=[], action="append", help="Glob pattern for folders to include", dest="includeFolders")
parser.add_argument("-E", "--exclude-folders"   , default=[], action="append", help="Glob pattern for folders to exclude", dest="excludeFolders")
parser.add_argument("-n", "--files-newer-than"  , default=""                 , help="Copy only files newer then this date", dest="filesNewerThan")
parser.add_argument("-f", "--folders-newer-than", default=""                 , help="Copy only folders newer then this date", dest="foldersNewerThan")
parser.add_argument("-N", "--newer-than-newest" , action="store_true"        , help="Copy only files newer then the newest file in the local folder", dest="newerThanNewest")
parser.add_argument("-R", "--recursive"         , action="store_true"        , help="Recurse into subdirectories")
parser.add_argument("-v", "--verbose"           , action="store_true"        , help="Print verbose information. Good for debugging")
parser.add_argument("-s", "--silent"            , action="store_true"        , help="Print only errors")
parser.add_argument("-P", "--port"              , default=22, type=int       , help="Remote port (default: 22)")
parser.add_argument("-T", "--timeout"           , default=1, type=float      , help="TCP 3-way handshake timeout in seconds (default: 1)")
parser.add_argument("-t", "--preserve-times"    , action="store_true"        , help="If set, modification times will be preserved", dest="preserveTimes")
parser.add_argument("-d", "--dont-close"        , action="store_true"        , help="Don't auto-close console window at the end if no error occurred. You will have to close it manually or by pressing ENTER", dest="dontClose")

args = parser.parse_args()

username         : str         = args.username
hostname         : str         = args.hostname
password         : str         = args.password
localFolder      : str         = args.localFolder
remoteFolder     : str         = args.remoteFolder
includeFiles     : list  [str] = args.includeFiles
excludeFiles     : list  [str] = args.excludeFiles
includeFolders   : list  [str] = args.includeFolders
excludeFolders   : list  [str] = args.excludeFolders
newerThanNewest  : bool        = args.newerThanNewest
recursive        : bool        = args.recursive
verbose          : bool        = args.verbose
silent           : bool        = args.silent
filesNewerThan   : str         = args.filesNewerThan
foldersNewerThan : str         = args.foldersNewerThan
port             : int         = args.port
timeout          : float       = args.timeout
preserveTimes    : bool        = args.preserveTimes
dontClose        : bool        = args.dontClose

if silent and verbose:
	raise SimpleError("-s/--silent and -v/--verbose options cannot both be specified at the same time")

if not os.path.isdir(localFolder):
	raise SimpleError(f'Folder "{localFolder}" does not exist or is not a folder')
else:
	localFolder = localFolder.replace("\\", "/")

dateFormats = [
	"%Y",
	"%Y-%m",
	"%Y-%m-%d",
	"%Y-%m-%d %H",
	"%Y-%m-%d %H:%M",
	"%Y-%m-%d %H:%M:%S",
]

filesNewerThanDate = 0
if filesNewerThan:
	for format in dateFormats:
		try:
			filesNewerThanDate = datetime.strptime(filesNewerThan, format).timestamp()
			break
		except ValueError:
			pass
	if not filesNewerThanDate:
		raise SimpleError(f'Incorrect -n/--files-newer-than parameter: {filesNewerThan}')

if verbose:
	print(f'Correctly parsed -n/--files-newer-than parameter "{filesNewerThan}" as {datetime.fromtimestamp(filesNewerThanDate)}')

foldersNewerThanDate = 0
if foldersNewerThan:
	for format in dateFormats:
		try:
			foldersNewerThanDate = datetime.strptime(foldersNewerThan, format).timestamp()
			break
		except ValueError:
			pass
	if not foldersNewerThanDate:
		raise SimpleError(f'Incorrect -f/--folders-newer-than parameter: {foldersNewerThan}')

if verbose:
	print(f'Correctly parsed -f/--folders-newer-than parameter "{foldersNewerThan}" as {datetime.fromtimestamp(foldersNewerThanDate)}')

defaultFileMatch = True
if includeFiles and excludeFiles:
	iIdx1 = iIdx2 = eIdx1 = eIdx2 = 10**10
	try:
		iIdx1 = sys.argv.index("-i")
	except ValueError: pass
	try:
		iIdx2 = sys.argv.index("--include-files")
	except ValueError: pass
	includePos = min(iIdx1, iIdx2)

	try:
		eIdx1 = sys.argv.index("-e")
	except ValueError: pass
	try:
		eIdx2 = sys.argv.index("--exclude-files")
	except ValueError: pass
	excludePos = min(eIdx1, eIdx2)

	# if exclude was first - match everything by default, if include was first - match nothing by default
	defaultFileMatch = excludePos < includePos

if verbose:
	print(f'By default all files will be {"included" if defaultFileMatch else "exluded"}')

def fileMatch(filename: str):
	for pattern in includeFiles:
		if fnmatchcase(filename, pattern):
			return True

	for pattern in excludeFiles:
		if fnmatchcase(filename, pattern):
			return False

	return defaultFileMatch

defaultFolderMatch = True
if includeFolders and excludeFolders:
	iIdx1 = iIdx2 = eIdx1 = eIdx2 = 10**10
	try:
		iIdx1 = sys.argv.index("-I")
	except ValueError: pass
	try:
		iIdx2 = sys.argv.index("--include-folders")
	except ValueError: pass
	includePos = min(iIdx1, iIdx2)

	try:
		eIdx1 = sys.argv.index("-E")
	except ValueError: pass
	try:
		eIdx2 = sys.argv.index("--exclude-folders")
	except ValueError: pass
	excludePos = min(eIdx1, eIdx2)

	# if exclude was first - match everything by default, if include was first - match nothing by default
	defaultFolderMatch = excludePos < includePos

if verbose:
	print(f'By default all folders will be {"included" if defaultFolderMatch else "exluded"}')

def folderMatch(foldername: str):
	for pattern in includeFolders:
		if fnmatchcase(foldername, pattern):
			return True

	for pattern in excludeFolders:
		if fnmatchcase(foldername, pattern):
			return False

	return defaultFolderMatch

ssh = getSSH(username, hostname, password, timeout, port, silent)
sftp = ssh.open_sftp()

try:
	assertRemoteFolderExists(sftp, remoteFolder)
	remoteFolder = remoteFolder.replace("\\", "/")

	def recursive_copy(remoteFolderParam: str, localFolderParam: str):
		if verbose:
			print(f"Entering remote folder: {remoteFolderParam}")
		newestLocalDate = 0
		if newerThanNewest:
			if verbose:
				print(f"Scanning local folder: {localFolderParam}")
			fileCount = 0
			with os.scandir(localFolderParam) as iter:
				for entry in iter:
					if entry.is_file():
						fileCount += 1
						if newestLocalDate < entry.stat().st_mtime:
							newestLocalDate = entry.stat().st_mtime
			if verbose:
				print(f'It has {fileCount} files {f"and the newest from them has date {datetime.fromtimestamp(newestLocalDate)} -> newestLocalDate" if fileCount else ""}')
		for entry in sftp.listdir_attr(remoteFolderParam):
			name = entry.filename
			if verbose:
				relPath = os.path.relpath(posixpath.join(remoteFolderParam, name), remoteFolder)
			if isDir(entry) and foldersNewerThanDate <= entry.st_mtime and folderMatch(name):
				newLocalFolder = posixpath.join(localFolderParam, name)
				os.makedirs(newLocalFolder, exist_ok=True)
				if recursive:
					newRemoteFolder = posixpath.join(remoteFolderParam, name)
					recursive_copy(newRemoteFolder, newLocalFolder)
			elif isFile(entry) and newestLocalDate <= entry.st_mtime and filesNewerThanDate <= entry.st_mtime and fileMatch(name):
				locPath = posixpath.join(localFolderParam, name)
				remPath = posixpath.join(remoteFolderParam, name)
				# if not os.path.exists(locPath) or modifiedDate(os.stat(locPath)) < modifiedDate(fileInfo):
				if not os.path.exists(locPath):
					if not silent:
						print(clr(os.path.relpath(remPath, remoteFolder), "green"))
					sftp.get(remPath, locPath)
					if preserveTimes:
						os.utime(locPath, (entry.st_atime, entry.st_mtime))
				elif verbose:
					print(f"{relPath} - skipping because it exists")
			elif verbose:
				if isDir(entry):
					if not (foldersNewerThanDate <= entry.st_mtime):
						print(f'{relPath} - skipping because it ({datetime.fromtimestamp(entry.st_mtime)}) is older than -f/--folders-newer-than parameter')
					elif not folderMatch(name):
						print(f"{relPath} - skipping because folderMatch returned False")
					else:
						print(f"{relPath} - skipping folder because of unknown reason") # This shouldn't happen
				elif isFile(entry):
					if not (newestLocalDate <= entry.st_mtime):
						print(f'{relPath} - skipping because it ({datetime.fromtimestamp(entry.st_mtime)}) is older than newestLocalDate')
					elif not (filesNewerThanDate <= entry.st_mtime):
						print(f'{relPath} - skipping because it ({datetime.fromtimestamp(entry.st_mtime)}) is older than -n/--files-newer-than parameter')
					elif not fileMatch(name):
						print(f"{relPath} - skipping because fileMatch returned False")
					else:
						print(f"{relPath} - skipping file because of unknown reason") # This shouldn't happen
				else:
					print(f"{relPath} - skipping because it is not a file nor folder")

	if not silent:
		print(f"Local folder: {localFolder}")
		print(f"Remote folder: {remoteFolder}")
		print("Copying files:\n")

	recursive_copy(remoteFolder, localFolder)

	if not silent:
		print(f"\nExecution time: {time.time() - start:.3f} s")

	if dontClose:
		if silent:
			input("")
		else:
			input(clr("\nPress ENTER to continue...", "green"))
except SimpleError as e:
	raise e
finally:
	sftp.close()
	ssh.close()
