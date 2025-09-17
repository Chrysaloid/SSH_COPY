# Version: 2.0.0

from termcolor import colored as clr, cprint
import os
import paramiko
import argparse
import time
from fnmatch import fnmatchcase
import sys
from datetime import datetime
import posixpath
from typing import Callable, Tuple
import shutil
import subprocess
from collections import defaultdict
from itertools import chain

start = time.time()

from SimpleError import SimpleError
from sshUtils import getSSH, remoteIsWindows, isFolderCaseSensitive
from getPlatform import WINDOWS
from fileUtils import isFile, isDir, assertRemoteFolderExists, modifiedDate
from LocalSFTPAttributes import local_listdir_attr

TITLE = "SSH SYNC"

if WINDOWS:
	import ctypes
	ctypes.windll.kernel32.SetConsoleTitleW(TITLE) # Hide title from shortcut
	os.system("color")
else:
	print(f"\33]0;{TITLE}\a", end="", flush=True) # Hide title

parser = argparse.ArgumentParser(description="Parse sync details")

parser.add_argument("-l", "--local-folder" , required=True, help="Local folder's absolute path", dest="localFolder")
parser.add_argument("-r", "--remote-folder", required=True, help="Remote (or local) folder's absolute path", dest="remoteFolder")

parser.add_argument("-u", "--username"                 , default=""                            , help="Remote username")
parser.add_argument("-H", "--hostname"                 , default=""                            , help="Remote host's address")
parser.add_argument("-p", "--password"                 , default=""                            , help="Remote password")
parser.add_argument("-i", "--include-files"            , default=[], action="extend", nargs="*", help="Glob patterns for files to include in copy/sync", dest="includeFiles")
parser.add_argument("-e", "--exclude-files"            , default=[], action="extend", nargs="*", help="Glob patterns for files to exclude in copy/sync", dest="excludeFiles")
parser.add_argument("-I", "--include-folders"          , default=[], action="extend", nargs="*", help="Glob patterns for folders to include in copy/sync", dest="includeFolders")
parser.add_argument("-E", "--exclude-folders"          , default=[], action="extend", nargs="*", help="Glob patterns for folders to exclude in copy/sync", dest="excludeFolders")
parser.add_argument("-n", "--files-newer-than"         , default=""                            , help="Copy/Sync only files newer then this date", dest="filesNewerThan")
parser.add_argument("-f", "--folders-newer-than"       , default=""                            , help="Copy/Sync only folders newer then this date", dest="foldersNewerThan")
parser.add_argument("-F", "--force"                    , action="store_true"                   , help="Force copying of source files even if they are older then destination files", dest="force")
parser.add_argument("-N", "--newer-than-newest-file"   , action="store_true"                   , help="Copy only files newer then the newest file in the destination folder", dest="newerThanNewestFile")
parser.add_argument("-M", "--newer-than-newest-folder" , action="store_true"                   , help="Copy only files newer then the newest folder in the destination folder", dest="newerThanNewestFolder")
parser.add_argument("-D", "--dont-filter-dest"         , action="store_false"                  , help="Don't filter the destination files/folders WHEN SEARCHING FOR THE NEWEST FILE", dest="filterDest")
parser.add_argument("-R", "--recursive"                , default=0, nargs="?", type=int        , help="Recurse into subdirectories. Optionaly take max recursion depth as parameter", dest="maxRecursionDepth")
parser.add_argument("-v", "--verbose"                  , action="store_true"                   , help="Print verbose information. Good for debugging")
parser.add_argument("-s", "--silent"                   , action="store_true"                   , help="Print only errors")
parser.add_argument("-P", "--port"                     , default=22, type=int                  , help="Remote port (default: 22)")
parser.add_argument("-T", "--timeout"                  , default=1, type=float                 , help="TCP 3-way handshake timeout in seconds (default: 1)")
parser.add_argument("-t", "--preserve-times"           , action="store_true"                   , help="If set, modification times will be preserved", dest="preserveTimes")
parser.add_argument("-d", "--dont-close"               , action="store_true"                   , help="Don't auto-close console window at the end if no error occurred. You will have to close it manually or by pressing ENTER", dest="dontClose")

args = parser.parse_args()

username              : str         = args.username
hostname              : str         = args.hostname
password              : str         = args.password
localFolder           : str         = args.localFolder
remoteFolder          : str         = args.remoteFolder
includeFiles          : list  [str] = args.includeFiles
excludeFiles          : list  [str] = args.excludeFiles
includeFolders        : list  [str] = args.includeFolders
excludeFolders        : list  [str] = args.excludeFolders
force                 : bool        = args.force
newerThanNewestFile   : bool        = args.newerThanNewestFile
newerThanNewestFolder : bool        = args.newerThanNewestFolder
filterDest            : bool        = args.filterDest
maxRecursionDepth     : int         = args.maxRecursionDepth
verbose               : bool        = args.verbose
silent                : bool        = args.silent
filesNewerThan        : str         = args.filesNewerThan
foldersNewerThan      : str         = args.foldersNewerThan
port                  : int         = args.port
timeout               : float       = args.timeout
preserveTimes         : bool        = args.preserveTimes
dontClose             : bool        = args.dontClose

if maxRecursionDepth is None: # Argument with no parameter mean no recursion limit
	maxRecursionDepth = sys.maxsize
elif maxRecursionDepth < 0:
	raise SimpleError("-R/--recursive option's parameter cannot be negative")

if any((username, hostname, password)) and not all((username, hostname, password)):
	raise SimpleError("If any of the parameters -u/--username, -H/--hostname, -p/--password is specified then all of them must be specified")
REMOTE_IS_REMOTE = bool(username)

if silent and verbose:
	raise SimpleError("-s/--silent and -v/--verbose options cannot both be specified at the same time")

if not os.path.isdir(localFolder):
	raise SimpleError(f'Folder "{localFolder}" does not exist or is not a folder')
else:
	localFolder = localFolder.replace("\\", "/")
remoteFolder = remoteFolder.replace("\\", "/")

dateFormats = [
	"%Y",
	"%Y-%m",
	"%Y-%m-%d",
	"%Y-%m-%d %H",
	"%Y-%m-%d %H:%M",
	"%Y-%m-%d %H:%M:%S",
]
def preProcessFilesOrFolders(
		strName: str,
		includeParamNames: tuple[str],
		excludeParamNames: tuple[str],
		newerThanParamName: str,
		newerThan: str,
		include: list[str],
		exclude: list[str]
	) -> Tuple[int, Callable[[int], str]]:
	newerThanDate = 0
	if newerThan:
		for format in dateFormats:
			try:
				newerThanDate = datetime.strptime(newerThan, format).timestamp()
				break
			except ValueError:
				pass
		if not newerThanDate:
			raise SimpleError(f'Incorrect {newerThanParamName} parameter: {newerThan}')

	if verbose:
		print(f'Correctly parsed {newerThanParamName} parameter "{newerThan}" as {datetime.fromtimestamp(newerThanDate)}')

	defaultMatch = True
	if include or exclude:
		includePos = excludePos = 10**10

		if include:
			for name in includeParamNames:
				try:
					idx = sys.argv.index(name)
					if includePos > idx:
						includePos = idx
				except ValueError: pass

		if exclude:
			for name in excludeParamNames:
				try:
					idx = sys.argv.index(name)
					if excludePos > idx:
						excludePos = idx
				except ValueError: pass

		# if exclude was first - match everything by default, if include was first - match nothing by default
		defaultMatch = excludePos < includePos

	if verbose:
		print(f'By default all {strName}s will be {"included" if defaultMatch else "exluded"}')

	def match(name: str) -> bool:
		for pattern in include:
			if fnmatchcase(name, pattern):
				return True

		for pattern in exclude:
			if fnmatchcase(name, pattern):
				return False

		return defaultMatch

	return newerThanDate, match

filesNewerThanDate  , fileMatch   = preProcessFilesOrFolders("file"  , ("-i", "--include-files")  , ("-e", "--exclude-files")  , "-n/--files-newer-than"  , filesNewerThan  , includeFiles  , excludeFiles  )
foldersNewerThanDate, folderMatch = preProcessFilesOrFolders("folder", ("-I", "--include-folders"), ("-E", "--exclude-folders"), "-f/--folders-newer-than", foldersNewerThan, includeFolders, excludeFolders)

try:
	localIdx = sys.argv.index("-l")
except ValueError:
	localIdx = sys.argv.index("--local-folder")
try:
	remoteIdx = sys.argv.index("-r")
except ValueError:
	remoteIdx = sys.argv.index("--remote-folder")
LOCAL_IS_SOURCE = localIdx < remoteIdx
# REMOTE_IS_SOURCE = not LOCAL_IS_SOURCE

def localMkdir(path: str):
	""" Returns True if folder was created and False if it already exists """
	try:
		os.mkdir(path)
		return True
	except FileExistsError:
		return False

if REMOTE_IS_REMOTE: # remoteFolder REALLY refers to a REMOTE folder
	ssh = getSSH(username, hostname, password, timeout, port, silent)
	sftp = ssh.open_sftp()

	assertRemoteFolderExists(sftp, remoteFolder)

	def remoteMkdir(path):
		""" Returns True if folder was created and False if it already exists """
		try:
			sftp.mkdir(path)
			return True
		except IOError:
			return False

	if LOCAL_IS_SOURCE:
		sourceFolderIter = local_listdir_attr
		destFolderIter = sftp.listdir_attr

		sourceMkdir = localMkdir
		destMkdir = remoteMkdir

		sourceUtime = os.utime
		destUtime = sftp.utime

		copyFun = sftp.put
		SOURCE_IS_NOT_WINDOWS_AND_DEST_IS_WINDOWS = not WINDOWS and remoteIsWindows(ssh)
		def isDestFolderCaseSensitive(destFolderParam): return isFolderCaseSensitive(ssh, destFolderParam) # Only for Windows
	else:
		sourceFolderIter = sftp.listdir_attr
		destFolderIter = local_listdir_attr

		sourceMkdir = remoteMkdir
		destMkdir = localMkdir

		sourceUtime = sftp.utime
		destUtime = os.utime

		copyFun = sftp.get
		SOURCE_IS_NOT_WINDOWS_AND_DEST_IS_WINDOWS = not remoteIsWindows(ssh) and WINDOWS
		def isDestFolderCaseSensitive(destFolderParam): # Only for Windows
			try:
				result = subprocess.run(
					f'fsutil file queryCaseSensitiveInfo "{destFolderParam}" 2>&1',
					shell=True,
					capture_output=True,
					text=True,
					check=False
				)
				output = result.stdout
				outputProcessed = output.strip().lower()

				if outputProcessed.endswith("enabled."):
					return True
				if outputProcessed.endswith("disabled."):
					return False

				raise RuntimeError(f"Unexpected fsutil output:\n{output}")
			except FileNotFoundError:
				raise RuntimeError("fsutil not found. This script must run on Windows with fsutil available.")
else: # remoteFolder ACTUALLY refers to a LOCAL folder
	if not os.path.isdir(remoteFolder):
		raise SimpleError(f'Folder "{remoteFolder}" does not exist or is not a folder')

	sourceFolderIter = local_listdir_attr
	destFolderIter = local_listdir_attr

	sourceMkdir = localMkdir
	destMkdir = localMkdir

	sourceUtime = os.utime
	destUtime = os.utime

	copyFun = shutil.copy2
	SOURCE_IS_NOT_WINDOWS_AND_DEST_IS_WINDOWS = False
	# In theory the case-(in)sensitivity problem can arise even when copying files locally on Windows.
	# That is when someone used fsutil.exe to enable case-sensitivity for some folder, created some files there that
	# are case-insensitivly equal and then tried to use this script to copy files from that folder to some other folder
	# that was not modified with fsutil.exe.
	# But let's assume that a person that is wise enough to use fsutil.exe would be wise enough not to use this script
	# with that special folder as a source.

if LOCAL_IS_SOURCE:
	sourceFolder = localFolder
	destFolder   = remoteFolder
else:
	sourceFolder = remoteFolder
	destFolder   = localFolder

SOURCE_DESIGNATION = "local" if LOCAL_IS_SOURCE else ("remote" if REMOTE_IS_REMOTE else "local")
DEST_DESIGNATION = ("remote" if REMOTE_IS_REMOTE else "local") if LOCAL_IS_SOURCE else "local"

def innerFilterFun(entry: paramiko.SFTPAttributes):
	return isDir (entry) and foldersNewerThanDate <= entry.st_mtime and folderMatch(entry.filename) \
		 or isFile(entry) and filesNewerThanDate   <= entry.st_mtime and fileMatch  (entry.filename)

def filterFun(entry: paramiko.SFTPAttributes):
	val = innerFilterFun(entry)

	if verbose and not val:
		name = entry.filename
		if isDir(entry):
			if not (foldersNewerThanDate <= entry.st_mtime):
				print(f'{name} - skipping because it ({modifiedDate(entry)}) is not newer than -f/--folders-newer-than parameter')
			elif not folderMatch(name):
				print(f"{name} - skipping because folderMatch returned False")
			else:
				print(f"{name} - skipping folder because of unknown reason") # This shouldn't happen
		elif isFile(entry):
			if not (filesNewerThanDate <= entry.st_mtime):
				print(f'{name} - skipping because it ({modifiedDate(entry)}) is not newer than -n/--files-newer-than parameter')
			elif not fileMatch(name):
				print(f"{name} - skipping because fileMatch returned False")
			else:
				print(f"{name} - skipping file because of unknown reason") # This shouldn't happen
		else:
			print(f"{name} - skipping because it is not a file nor folder")

	return val

def recursiveCopy(sourceFolderParam: str, destFolderParam: str, depth: int = 0):
	if verbose:
		print(f"Entering {SOURCE_DESIGNATION} source folder: {sourceFolderParam}")
		print(f"Scanning {DEST_DESIGNATION} destination folder: {destFolderParam}")

	sourceEntries = tuple(filter(filterFun, sourceFolderIter(sourceFolderParam)))

	if sourceEntries:
		if SOURCE_IS_NOT_WINDOWS_AND_DEST_IS_WINDOWS:
			errorOccured = False
			try:
				caseSense = isDestFolderCaseSensitive(destFolderParam)
			except Exception as e:
				errorOccured = True
				if not silent:
					cprint(f'Error occured when determining if destination folder {f'"{destFolderParam}"' if not verbose else ""} is case-sensitive:\n{e}', "red")
				caseSense = False # Good assumption as this is default on windows

			if not caseSense:
				caselessEntries = defaultdict(list)
				for entry in sourceEntries:
					caselessEntries[entry.filename.lower()].append(entry)
				caseDuplicates: list[list[paramiko.SFTPAttributes]] = []
				for entries in caselessEntries.values():
					if len(entries) > 1:
						caseDuplicates.append(entries)
				if caseDuplicates:
					if not silent:
						print(f"Following files in the source folder have names that only differ in letter case:")
						for i, entries in enumerate(caseDuplicates, start=1):
							print(f"Group {i}:")
							for entry in entries:
								print(entry.filename)
						cprint(f"And they will not be copied unless you change their names or enable case-sensitivity in the destination Windows folder with fsutil.exe", "yellow")
					caseDuplicatesFlattened = tuple(chain.from_iterable(caseDuplicates))
					sourceEntries = tuple(filter(lambda e: e not in caseDuplicatesFlattened, sourceEntries))
					if not sourceEntries:
						return
				elif errorOccured:
					if not silent:
						cprint(f"...but it won't cause any problems because source files/folders are case-sensitivly unique", "green")

		destEntries = destFolderIter(destFolderParam) if newerThanNewestFile or newerThanNewestFolder or not force else () # Empty tuple

		newestDestDate = 0
		if newerThanNewestFile or newerThanNewestFolder: # find newest file/folder in the destination folder
			if filterDest:
				destEntries = tuple(filter(innerFilterFun, destEntries))
			entryCount = 0
			for entry in destEntries:
				if newerThanNewestFile and isFile(entry) or newerThanNewestFolder and isDir(entry):
					entryCount += 1
					if newestDestDate < entry.st_mtime:
						newestDestDate = entry.st_mtime
			if verbose:
				matching = " matching" if filterDest else ""
				filesFolders = "files/folders" if newerThanNewestFile and newerThanNewestFolder else ("files" if newerThanNewestFile else "folders")
				theNewest = f"and the newest from them has date {datetime.fromtimestamp(newestDestDate)} -> newestDestDate" if entryCount else ""
				print(f'Destination folder has {entryCount}{matching} {filesFolders} {theNewest}')

		destEntriesDict = {entry.filename: entry for entry in destEntries}

		for sourceEntry in sourceEntries:
			name = sourceEntry.filename
			if isDir(sourceEntry):
				newDestFolder = posixpath.join(destFolderParam, name)
				if name not in destEntriesDict:
					if destMkdir(newDestFolder) and preserveTimes:
						destUtime(newDestFolder, (sourceEntry.st_atime, sourceEntry.st_mtime))
				if depth < maxRecursionDepth:
					newSourceFolder = posixpath.join(sourceFolderParam, name)
					recursiveCopy(newSourceFolder, newDestFolder, depth + 1)
			elif isFile(sourceEntry) and newestDestDate < sourceEntry.st_mtime:
				destEntry = destEntriesDict.get(name)
				if force or not destEntry or destEntry.st_mtime < sourceEntry.st_mtime:
					sourcePath = posixpath.join(sourceFolderParam, name)
					destPath = posixpath.join(destFolderParam, name)
					if not silent:
						print(clr(sourcePath.replace(sourceFolder, "", count=1), "green"))
					copyFun(sourcePath, destPath)
					if preserveTimes:
						destUtime(destPath, (sourceEntry.st_atime, sourceEntry.st_mtime))
				elif verbose:
					if force:
						print(f"{name} - skipping because it exists")
					elif not (destEntry.st_mtime < sourceEntry.st_mtime):
						print(f"{name} - skipping because it is not newer than the destination")
			elif verbose:
				if isFile(sourceEntry):
					if not (newestDestDate < sourceEntry.st_mtime):
						print(f'{name} - skipping because it ({modifiedDate(sourceEntry)}) is not newer than newestDestDate')
					else:
						print(f"{name} - skipping file because of unknown reason") # This shouldn't happen

try:
	if not silent:
		print(f"Copying from {SOURCE_DESIGNATION} to {DEST_DESIGNATION}")
		print(f"Source folder: {sourceFolder}")
		print(f"Destination folder: {destFolder}")
		print("Copying files:\n")

	recursiveCopy(sourceFolder, destFolder, 0)

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
	if REMOTE_IS_REMOTE:
		sftp.close()
		ssh.close()
