# Version: 2.4.0

# region #* IMPORTS
from termcolor import colored as clr, cprint
import os
import paramiko
import argparse
import time
from fnmatch import fnmatchcase, fnmatch
import sys
from datetime import datetime
import posixpath
from typing import Callable, Tuple
import shutil
from collections import defaultdict
from itertools import chain
from enum import IntEnum, auto

start = time.time()

from SimpleError import SimpleError
from sshUtils import (
	getSSH,
	remoteIsWindows,
	isFolderCaseSensitive as isRemoteFolderCaseSensitive,
	assertRemoteFolderExists,
	remoteMkdir as remoteMkdirBase,
	remote_listdir_attr as remote_listdir_attr_base,
	remoteHasPython,
	ensureRemoteFolderExists
)
from getPlatform import WINDOWS
from fileUtils import isFile, isDir, modifiedDate, assertFolderExists, ensureFolderExists, mkdir as localMkdir
from LocalSFTPAttributes import local_listdir_attr
from isFolderCaseSensitive import isFolderCaseSensitive as isLocalFolderCaseSensitive
# endregion

TITLE = "SSH SYNC"

if WINDOWS:
	import ctypes
	ctypes.windll.kernel32.SetConsoleTitleW(TITLE) # Hide title from shortcut
	os.system("color")
else:
	print(f"\33]0;{TITLE}\a", end="", flush=True) # Hide title

# region #* PARAMETER PARSING
parser = argparse.ArgumentParser(description="Copy or sync files between folders on remote or local machines")

parser.add_argument("-l", "--local-folder" , required=True, help="Local folder's absolute path", dest="localFolder")
parser.add_argument("-r", "--remote-folder", required=True, help="Remote (or local) folder's absolute path", dest="remoteFolder")

class NameFilter:
	def __init__(self, pattern: str, matchVal: bool, matchingFunc: Callable):
		self.pattern = pattern
		self.matchVal = matchVal
		self.matchingFunc = matchingFunc

class IncludeExcludeAction(argparse.Action):
	destDefaults = {}

	def __init__(self, option_strings: list[str], dest, **kwargs):
		super().__init__(option_strings, dest, **kwargs)

		if len(option_strings) != 2:
			raise ValueError(f"IncludeExcludeAction should always have short and long parameter names specified")

		longName = max(option_strings, key=lambda op: len(op))

		self.matchVal = longName.startswith("--include")
		self.matchingFunc = fnmatchcase if longName.endswith("case") else fnmatch

	def __call__(self, parser, namespace, values, option_string=None):
		# Ensure the target list exists
		items = getattr(namespace, self.dest, None)
		if items is None:
			items = []
			setattr(namespace, self.dest, items)

		if self.dest not in IncludeExcludeAction.destDefaults:
			IncludeExcludeAction.destDefaults[self.dest] = self.matchVal

		for pattern in values:
			items.append(NameFilter(pattern, self.matchVal, self.matchingFunc))

class MODE(IntEnum):
	UPDATE = auto()
	COPY = auto()

MODE_DICT = {mode.name.lower(): mode for mode in MODE}

def getMode(modeStr: str):
	modeStr = modeStr.lower()
	try:
		return MODE_DICT[modeStr].value
	except:
		raise SimpleError(f'-m/--mode option should be one of the values: {",".join(MODE_DICT.keys())}')

parser.add_argument("-i", "--include-files"       , default=[], action=IncludeExcludeAction, nargs="*", help="Glob patterns for files to include in copy/sync"                   , dest="inExcludeFiles"  )
parser.add_argument("-e", "--exclude-files"       , default=[], action=IncludeExcludeAction, nargs="*", help="Glob patterns for files to exclude in copy/sync"                   , dest="inExcludeFiles"  )
parser.add_argument("-c", "--include-files-case"  , default=[], action=IncludeExcludeAction, nargs="*", help="Glob patterns for files to include in copy/sync (case-sensitive)"  , dest="inExcludeFiles"  )
parser.add_argument("-a", "--exclude-files-case"  , default=[], action=IncludeExcludeAction, nargs="*", help="Glob patterns for files to exclude in copy/sync (case-sensitive)"  , dest="inExcludeFiles"  )
parser.add_argument("-I", "--include-folders"     , default=[], action=IncludeExcludeAction, nargs="*", help="Glob patterns for folders to include in copy/sync"                 , dest="inExcludeFolders")
parser.add_argument("-E", "--exclude-folders"     , default=[], action=IncludeExcludeAction, nargs="*", help="Glob patterns for folders to exclude in copy/sync"                 , dest="inExcludeFolders")
parser.add_argument("-C", "--include-folders-case", default=[], action=IncludeExcludeAction, nargs="*", help="Glob patterns for folders to include in copy/sync (case-sensitive)", dest="inExcludeFolders")
parser.add_argument("-A", "--exclude-folders-case", default=[], action=IncludeExcludeAction, nargs="*", help="Glob patterns for folders to exclude in copy/sync (case-sensitive)", dest="inExcludeFolders")
parser.add_argument("-u", "--username"                 , default=""                    , help="Remote username")
parser.add_argument("-H", "--hostname"                 , default=""                    , help="Remote host's address")
parser.add_argument("-p", "--password"                 , default=""                    , help="Remote password")
parser.add_argument("-n", "--files-newer-than"         , default=""                    , help="Copy/Sync only files newer then this date", dest="filesNewerThan")
parser.add_argument("-f", "--folders-newer-than"       , default=""                    , help="Copy/Sync only folders newer then this date", dest="foldersNewerThan")
parser.add_argument("-F", "--force"                    , action="store_true"           , help="Force copying of source files even if they are older then destination files", dest="force")
parser.add_argument("-N", "--newer-than-newest-file"   , action="store_true"           , help="Copy only files newer then the newest file in the destination folder", dest="newerThanNewestFile")
parser.add_argument("-M", "--newer-than-newest-folder" , action="store_true"           , help="Copy only files newer then the newest folder in the destination folder", dest="newerThanNewestFolder")
parser.add_argument("-D", "--dont-filter-dest"         , action="store_false"          , help="Don't filter the destination files/folders WHEN SEARCHING FOR THE NEWEST FILE", dest="filterDest")
parser.add_argument("-R", "--recursive"                , default=0, nargs="?", type=int, help="Recurse into subdirectories. Optionaly takes max recursion depth as parameter", dest="maxRecursionDepth")
parser.add_argument("-x", "--create-max-rec-folders"   , action="store_true"           , help="Create folders at max recursion depth", dest="createMaxRecFolders")
parser.add_argument("-v", "--verbose"                  , action="store_true"           , help="Print verbose information. Good for debugging")
parser.add_argument("-s", "--silent"                   , action="store_true"           , help="Print only errors")
parser.add_argument("-P", "--port"                     , default=22, type=int          , help="Remote port (default: 22)")
parser.add_argument("-T", "--timeout"                  , default=1, type=float         , help="TCP 3-way handshake timeout in seconds (default: 1)")
parser.add_argument("-t", "--dont-preserve-times"      , action="store_false"          , help="If set, modification times will not be preserved", dest="preserveTimes")
parser.add_argument("-d", "--dont-close"               , action="store_true"           , help="Don't auto-close console window at the end if no error occurred. You will have to close it manually or by pressing ENTER", dest="dontClose")
parser.add_argument("-m", "--mode"                     , default="COPY"                , help=f'One of values: {",".join(MODE_DICT.keys())} (Default: copy)')
parser.add_argument("-S", "--create-dest-folder"       , action="store_true"           , help="If destination folder doesn't exists, create it and all its parents (like mkdir (-p on Linux)). If not set throw an error if the folder doesn not exist", dest="createDestFolder")
parser.add_argument("-l", "--fast-listdir-attr"        , action="store_true"           , help="If you copy/sync folder(s) containing more than 1000 entries this may be faster. Requires Python 3 on remote host", dest="fastListdirAttr")

args = parser.parse_args()

username              : str                = args.username
hostname              : str                = args.hostname
password              : str                = args.password
localFolder           : str                = args.localFolder
remoteFolder          : str                = args.remoteFolder
inExcludeFiles        : list  [NameFilter] = args.inExcludeFiles
inExcludeFolders      : list  [NameFilter] = args.inExcludeFolders
force                 : bool               = args.force
newerThanNewestFile   : bool               = args.newerThanNewestFile
newerThanNewestFolder : bool               = args.newerThanNewestFolder
filterDest            : bool               = args.filterDest
maxRecursionDepth     : int                = args.maxRecursionDepth
createMaxRecFolders   : bool               = args.createMaxRecFolders
verbose               : bool               = args.verbose
silent                : bool               = args.silent
filesNewerThan        : str                = args.filesNewerThan
foldersNewerThan      : str                = args.foldersNewerThan
port                  : int                = args.port
timeout               : float              = args.timeout
preserveTimes         : bool               = args.preserveTimes
dontClose             : bool               = args.dontClose
mode                  : str                = args.mode
createDestFolder      : bool               = args.createDestFolder
fastListdirAttr       : bool               = args.fastListdirAttr
# endregion

# region #* PARAMETER VALIDATION
mode: int = getMode(mode)

if maxRecursionDepth is None: # Argument with no parameter mean no recursion limit
	maxRecursionDepth = sys.maxsize
elif maxRecursionDepth < 0:
	raise SimpleError("-R/--recursive option's parameter cannot be negative")
elif maxRecursionDepth == 0: # -R/--recursive was not specified at all
	if (inExcludeFolders or foldersNewerThan) and not createMaxRecFolders and not silent:
		cprint("Warning: Folder filtering options don't work if -R/--recursive or -x/--create-max-rec-folders was not specified", "yellow")

if any((username, hostname, password)) and not all((username, hostname, password)):
	raise SimpleError("If any of the parameters -u/--username, -H/--hostname, -p/--password is specified then all of them must be specified")
REMOTE_IS_REMOTE = bool(username)

if silent and verbose:
	raise SimpleError("-s/--silent and -v/--verbose options cannot both be specified at the same time")

localFolder = os.path.abspath(localFolder).replace("\\", "/").rstrip("/")
remoteFolder = remoteFolder.replace("\\", "/").rstrip("/")

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
		strParam: str,
		newerThanParamName: str,
		newerThan: str,
		inExclude: list[NameFilter]
	) -> Tuple[int, Callable[[str], bool]]:
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

	defaultMatch = IncludeExcludeAction.destDefaults.get(strParam, True)

	if verbose:
		print(f'By default all {strName}s will be {"included" if defaultMatch else "exluded"}')

	if inExclude:
		def match(name: str) -> bool:
			for filterObj in inExclude:
				if filterObj.matchingFunc(name, filterObj.pattern):
					return filterObj.matchVal
			return defaultMatch
	else:
		def match(name: str) -> bool:
			return defaultMatch

	return int(newerThanDate), match

filesNewerThanDate  , fileMatch   = preProcessFilesOrFolders("file"  , "inExcludeFiles"  , "-n/--files-newer-than"  , filesNewerThan  , inExcludeFiles  )
foldersNewerThanDate, folderMatch = preProcessFilesOrFolders("folder", "inExcludeFolders", "-f/--folders-newer-than", foldersNewerThan, inExcludeFolders)

#* LOCAL/REMOTE FOLDER PARAMETER VALIDATION
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

if LOCAL_IS_SOURCE:
	sourceFolder = localFolder
	destFolder   = remoteFolder
else:
	sourceFolder = remoteFolder
	destFolder   = localFolder

if LOCAL_IS_SOURCE or not REMOTE_IS_REMOTE:
	assertFolderExists(sourceFolder)

if not LOCAL_IS_SOURCE or not REMOTE_IS_REMOTE:
	if createDestFolder:
		ensureFolderExists(destFolder)
	else:
		assertFolderExists(destFolder, "\nYou can create it by specifying the -S/--create-dest-folder parameter")

def isFolderCaseSensitiveBase(isWindows: bool, realFunc: Callable, realFuncArgs: tuple, folderType: str, path: str) -> tuple[bool, bool]: # errorOccured, caseSense
	if not isWindows:
		return (False, True)

	errorOccured = False
	try:
		caseSense = realFunc(*realFuncArgs)
	except Exception as e:
		errorOccured = True
		if not silent:
			cprint(f'Error occured when determining if {folderType} folder {f'"{path}"' if not verbose else ""} is case-sensitive:\n{e}', "red")
		caseSense = False # Good assumption as this is the default on windows

	return (errorOccured, caseSense)

if REMOTE_IS_REMOTE: # remoteFolder REALLY refers to a REMOTE folder
	ssh = getSSH(username, hostname, password, timeout, port, silent)
	sftp = ssh.open_sftp()

	if LOCAL_IS_SOURCE:
		if createDestFolder:
			ensureRemoteFolderExists(sftp, destFolder)
		else:
			assertRemoteFolderExists(sftp, destFolder, "\nYou can create it by specifying the -S/--create-dest-folder parameter")
	else:
		assertRemoteFolderExists(sftp, sourceFolder)

	def remoteMkdir(path): return remoteMkdirBase(sftp, path)

	if fastListdirAttr:
		pythonStr = remoteHasPython(ssh)
		def remote_listdir_attr(path: str): return remote_listdir_attr_base(ssh, path, pythonStr)
	else:
		remote_listdir_attr = sftp.listdir_attr

	if LOCAL_IS_SOURCE:
		sourceFolderIter = local_listdir_attr
		destFolderIter = remote_listdir_attr

		sourceMkdir = localMkdir
		destMkdir = remoteMkdir

		sourceUtime = os.utime
		destUtime = sftp.utime

		copyFun = sftp.put

		sourceIsWindows = WINDOWS
		destIsWindows = remoteIsWindows(ssh)

		# Only for Windows
		def isSourceFolderCaseSensitive(path: str): return isFolderCaseSensitiveBase(sourceIsWindows, isLocalFolderCaseSensitive, (path, False), "source", path)
		def isDestFolderCaseSensitive(path: str): return isFolderCaseSensitiveBase(destIsWindows, isRemoteFolderCaseSensitive, (ssh, path), "destination", path)
	else:
		sourceFolderIter = remote_listdir_attr
		destFolderIter = local_listdir_attr

		sourceMkdir = remoteMkdir
		destMkdir = localMkdir

		sourceUtime = sftp.utime
		destUtime = os.utime

		copyFun = sftp.get

		sourceIsWindows = remoteIsWindows(ssh)
		destIsWindows = WINDOWS

		def isSourceFolderCaseSensitive(path: str): return isFolderCaseSensitiveBase(sourceIsWindows, isRemoteFolderCaseSensitive, (ssh, path), "source", path)
		def isDestFolderCaseSensitive(path: str): return isFolderCaseSensitiveBase(destIsWindows, isLocalFolderCaseSensitive, (path, False), "destination", path)
else: # remoteFolder ACTUALLY refers to a LOCAL folder
	sourceFolderIter = local_listdir_attr
	destFolderIter = local_listdir_attr

	sourceMkdir = localMkdir
	destMkdir = localMkdir

	sourceUtime = os.utime
	destUtime = os.utime

	copyFun = shutil.copy2

	sourceIsWindows = WINDOWS
	destIsWindows = WINDOWS

	def isSourceFolderCaseSensitive(path: str): return isFolderCaseSensitiveBase(sourceIsWindows, isLocalFolderCaseSensitive, (path, False), "source", path)
	def isDestFolderCaseSensitive(path: str): return isFolderCaseSensitiveBase(destIsWindows, isLocalFolderCaseSensitive, (path, False), "destination", path)

SOURCE_DESIGNATION = "local" if LOCAL_IS_SOURCE else ("remote" if REMOTE_IS_REMOTE else "local")
DEST_DESIGNATION = ("remote" if REMOTE_IS_REMOTE else "local") if LOCAL_IS_SOURCE else "local"

DEST_FILTER_WARN = verbose and filterDest and any(filter(lambda f: f.matchingFunc is fnmatchcase, inExcludeFiles + inExcludeFolders))
# endregion

# region #* FILE COPYING
def innerFilterFun(entry: paramiko.SFTPAttributes) -> bool:
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

	match mode:
		case MODE.COPY:
			sourceEntries = tuple(filter(filterFun, sourceFolderIter(sourceFolderParam)))

			if sourceEntries:
				sourceErrorOccured, sourceCaseSense = isSourceFolderCaseSensitive(sourceFolderParam)
				destErrorOccured, destCaseSense = isDestFolderCaseSensitive(destFolderParam)
				# ANY_CASE_INSENSITIVE = not sourceCaseSense or not destCaseSense

				if sourceCaseSense and not destCaseSense: # Most probable scenario: copy from Linux to Windows
					caselessEntries = defaultdict(list)
					for entry in sourceEntries:
						caselessEntries[entry.filename.lower()].append(entry)
					caseDuplicates: list[list[paramiko.SFTPAttributes]] = []
					for entries in caselessEntries.values():
						if len(entries) > 1:
							caseDuplicates.append(entries)
					if caseDuplicates:
						if not silent:
							print(f'Following files/folders in the source folder "{sourceFolderParam}" have names that only differ in letter case:')
							for i, entries in enumerate(caseDuplicates, start=1):
								print(f"Group {i}:")
								for entry in entries:
									print(entry.filename)
							cprint(f"And they will not be copied unless you change their names or enable case-sensitivity in the destination Windows folder with fsutil.exe", "yellow")
						caseDuplicatesFlattened = tuple(chain.from_iterable(caseDuplicates))
						sourceEntries = tuple(filter(lambda e: e not in caseDuplicatesFlattened, sourceEntries))
						if not sourceEntries:
							return
					elif destErrorOccured:
						if not silent:
							cprint(f"...but it won't cause any problems because source files/folders are case-sensitivly unique", "green")

				destEntries = destFolderIter(destFolderParam) if newerThanNewestFile or newerThanNewestFolder or not force else () # Empty tuple

				newestDestDate = 0
				if newerThanNewestFile or newerThanNewestFolder: # find newest file/folder in the destination folder
					if DEST_FILTER_WARN and not destCaseSense:
						cprint("Warning: When searching for newest file in the destination folder you may have excluded some files/folders case-sensitivly but the folder is case-insensitive", "yellow")
					entryCount = 0
					for entry in (tuple(filter(innerFilterFun, destEntries)) if filterDest else destEntries):
						if newerThanNewestFile and isFile(entry) or newerThanNewestFolder and isDir(entry):
							entryCount += 1
							if newestDestDate < entry.st_mtime:
								newestDestDate = entry.st_mtime
					if verbose:
						matching = " matching" if filterDest else ""
						filesFolders = "files/folders" if newerThanNewestFile and newerThanNewestFolder else ("files" if newerThanNewestFile else "folders")
						theNewest = f"and the newest from them has date {datetime.fromtimestamp(newestDestDate)} -> newestDestDate" if entryCount else ""
						print(f'Destination folder has {entryCount}{matching} {filesFolders} {theNewest}')

				"""
				Explanation for following if staments containing destCaseSense:
				sourceCaseSense and destCaseSense: (i.e. Linux -> Linux) Both are case-sensitive so no need to normalize case
				sourceCaseSense and not destCaseSense: (i.e. Linux -> Windows) Case normalization necessary as Windows is case-insensitive
				not sourceCaseSense and destCaseSense: (i.e. Windows -> Linux) No need to normalize case as case-insensitive names are a subset of case-sensitive names
				not sourceCaseSense and not destCaseSense: (i.e. Windows -> Windows) Case normalization necessary as both are case-insensitive
				So we can se that case normalization is only necessary if not destCaseSense
				"""
				if destCaseSense:
					destEntriesDict = {entry.filename: entry for entry in destEntries}
				else:
					destEntriesDict = {entry.filename.lower(): entry for entry in destEntries}

				for sourceEntry in sourceEntries:
					name = sourceEntry.filename
					if isDir(sourceEntry) and (depth < maxRecursionDepth or createMaxRecFolders):
						newDestFolder = posixpath.join(destFolderParam, name)
						if (name if destCaseSense else name.lower()) not in destEntriesDict:
							if destMkdir(newDestFolder) and preserveTimes:
								destUtime(newDestFolder, (sourceEntry.st_atime, sourceEntry.st_mtime))
						if depth < maxRecursionDepth:
							newSourceFolder = posixpath.join(sourceFolderParam, name)
							recursiveCopy(newSourceFolder, newDestFolder, depth + 1)
					elif isFile(sourceEntry) and newestDestDate < sourceEntry.st_mtime:
						destEntry = destEntriesDict.get(name if destCaseSense else name.lower())
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
		case MODE.UPDATE:
			pass
		case _: # Shouldn't happen
			raise SimpleError(f"Invalid mode: {mode}")

if not silent:
	print(f"Copying from {SOURCE_DESIGNATION} to {DEST_DESIGNATION}")
	print(f"Source folder: {sourceFolder}")
	print(f"Destination folder: {destFolder}")
	print("Copying files:\n")

recursiveCopy(sourceFolder, destFolder, 0)

# the try...finally block is not needed because when an exception happens "the program ends, the
# Python process shuts down. As part of process teardown, the underlying socket to the SSH server is
# closed by the OS"
if REMOTE_IS_REMOTE:
	sftp.close()
	ssh.close()

if not silent:
	print(f"\nExecution time: {time.time() - start:.3f} s")

if dontClose:
	if silent:
		input("")
	else:
		input(clr("\nPress ENTER to continue...", "green"))
# endregion
