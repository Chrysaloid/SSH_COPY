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
from typing import Callable, Tuple, List
import shutil
from collections import defaultdict
from itertools import chain
from enum import IntEnum, auto
from types import SimpleNamespace

start = time.time()

from SimpleError import SimpleError
from sshUtils import (
	getSSH,
	remoteIsWindows,
	isFolderCaseSensitive as isRemoteFolderCaseSensitive,
	assertRemoteFolderExists,
	remoteMkdir as remoteMkdirBase,
	RemoteListDir,
	remoteHasPython,
	ensureRemoteFolderExists
)
from getPlatform import WINDOWS
from fileUtils import isFile, isDir, modifiedDate, assertFolderExists, ensureFolderExists, mkdir as localMkdir
from LocalSFTPAttributes import local_listdir_attr
from isFolderCaseSensitive import isFolderCaseSensitive as isLocalFolderCaseSensitive
from commonConstants import COLOR_OK, COLOR_ERROR, COLOR_WARN, COLOR_EMPHASIS
from argparseUtils import ArgumentParser_ColoredError, NoRepeatAction, NameFilter, IncludeExcludeAction
# endregion

TITLE = "SSH SYNC"
SOURCE_STR = "source"
DEST_STR   = "destination"

if WINDOWS:
	import ctypes
	ctypes.windll.kernel32.SetConsoleTitleW(TITLE) # Hide title from shortcut
	os.system("color")
else:
	print(f"\33]0;{TITLE}\a", end="", flush=True) # Hide title

# region #* PARAMETER PARSING
parser = ArgumentParser_ColoredError(description="Copy or sync files between folders on remote or local machines")

required = parser.add_argument_group("Required arguments")
parser._action_groups = [required, parser._optionals]

required.add_argument("-l", "--local-folder" , required=True, action=NoRepeatAction, help="Local folder's absolute path"            , dest="localFolder" , metavar="ABSOLUTE_PATH")
required.add_argument("-r", "--remote-folder", required=True, action=NoRepeatAction, help="Remote (or local) folder's absolute path", dest="remoteFolder", metavar="ABSOLUTE_PATH")

class MODE(IntEnum):
	SYNC = auto()
	COPY = auto()

MODE_DICT = {mode.name.lower(): mode for mode in MODE}

def getMode(modeStr: str):
	modeStr = modeStr.lower()
	try:
		return MODE_DICT[modeStr].value
	except:
		raise SimpleError(f'-m/--mode option should be one of the values: {",".join(MODE_DICT.keys())}')

class ACTION(IntEnum):
	NONE = auto()
	CONTINUE = auto()
	RETURN = auto()

parser._optionals.title = "Optional common arguments"

parser.add_argument("-i", "--include-files"       , default=[], action=IncludeExcludeAction, nargs="*", help="Glob patterns for files to include in copy/sync"                   , dest="inExcludeFiles"  , metavar=("PATTERN_1", "PATTERN_2"))
parser.add_argument("-e", "--exclude-files"       , default=[], action=IncludeExcludeAction, nargs="*", help="Glob patterns for files to exclude in copy/sync"                   , dest="inExcludeFiles"  , metavar=("PATTERN_1", "PATTERN_2"))
parser.add_argument("-c", "--include-files-case"  , default=[], action=IncludeExcludeAction, nargs="*", help="Glob patterns for files to include in copy/sync (case-sensitive)"  , dest="inExcludeFiles"  , metavar=("PATTERN_1", "PATTERN_2"))
parser.add_argument("-a", "--exclude-files-case"  , default=[], action=IncludeExcludeAction, nargs="*", help="Glob patterns for files to exclude in copy/sync (case-sensitive)"  , dest="inExcludeFiles"  , metavar=("PATTERN_1", "PATTERN_2"))
parser.add_argument("-I", "--include-folders"     , default=[], action=IncludeExcludeAction, nargs="*", help="Glob patterns for folders to include in copy/sync"                 , dest="inExcludeFolders", metavar=("PATTERN_1", "PATTERN_2"))
parser.add_argument("-E", "--exclude-folders"     , default=[], action=IncludeExcludeAction, nargs="*", help="Glob patterns for folders to exclude in copy/sync"                 , dest="inExcludeFolders", metavar=("PATTERN_1", "PATTERN_2"))
parser.add_argument("-C", "--include-folders-case", default=[], action=IncludeExcludeAction, nargs="*", help="Glob patterns for folders to include in copy/sync (case-sensitive)", dest="inExcludeFolders", metavar=("PATTERN_1", "PATTERN_2"))
parser.add_argument("-A", "--exclude-folders-case", default=[], action=IncludeExcludeAction, nargs="*", help="Glob patterns for folders to exclude in copy/sync (case-sensitive)", dest="inExcludeFolders", metavar=("PATTERN_1", "PATTERN_2"))
parser.add_argument("-u", "--username"                  , default=""                    , help="Remote username")
parser.add_argument("-H", "--hostname"                  , default=""                    , help="Remote host's address")
parser.add_argument("-p", "--password"                  , default=""                    , help="Remote password")
parser.add_argument("-P", "--port"                      , default=22, type=int          , help="Remote port (default: 22)")
parser.add_argument("-T", "--timeout"                   , default=1, type=float         , help="TCP 3-way handshake timeout in seconds (default: 1)", metavar="SECONDS")
parser.add_argument("-n", "--files-newer-than"          , default=""                    , help="Copy/Sync only files newer then this date"  , dest="filesNewerThan"  , metavar="DATE")
parser.add_argument("-f", "--folders-newer-than"        , default=""                    , help="Copy/Sync only folders newer then this date", dest="foldersNewerThan", metavar="DATE")
parser.add_argument("-R", "--recursive"                 , default=0, nargs="?", type=int, help="Recurse into subdirectories. Optionaly takes max recursion depth as parameter", dest="maxRecursionDepth", metavar="MAX_RECURSION_DEPTH")
parser.add_argument("-S", "--create-dest-folder"        , action="store_true"           , help="If destination folder doesn't exists, create it and all its parents (like mkdir (-p on Linux)). If not set terminate the script if the folder doesn not exist", dest="createDestFolder")
parser.add_argument("-x", "--create-max-rec-folders"    , action="store_true"           , help="Create folders at max recursion depth", dest="createMaxRecFolders")
parser.add_argument("-v", "--verbose"                   , action="store_true"           , help="Print verbose information. Good for debugging")
parser.add_argument("-s", "--silent"                    , action="store_true"           , help="Print only errors")
parser.add_argument("-t", "--dont-preserve-times"       , action="store_false"          , help="If set, modification times will not be preserved and instead files/folders will have current time set as their modification time", dest="preserveTimes")
parser.add_argument("-B", "--dont-preserve-permissions" , action="store_false"          , help="If set, permissions will not be preserved and instead files/folders will have default permissions set", dest="preservePermissions")
parser.add_argument("-d", "--dont-close"                , action="store_true"           , help="Don't auto-close console window at the end if no error occurred. You will have to close it manually or by pressing ENTER", dest="dontClose")
parser.add_argument("-b", "--fast-remote-listdir-attr"  , action="store_true"           , help="If you copy/sync folder(s) containing more than 5000 entries from/to remote location this may be faster. Requires Python 3 on remote host", dest="fastRemoteListdirAttr")
parser.add_argument("-k", "--listdir-attr-fallback"     , action="store_true"           , help='Instead of terminating the script if remote does not have Python 3, fall back to "slow" listdir-attr. Only applicable if -b/--fast-remote-listdir-attr was set', dest="listdirAttrFallback")
parser.add_argument("-K", "--end-on-inaccessible-entry" , action="store_true"           , help="Terminate the script if it does not have enough perrmisions to access any encountered file/folder (local or remote). If not set ignore such cases but print a warning", dest="endOnInaccessibleEntry")
parser.add_argument("-L", "--end-on-file-onto-folder"   , action="store_true"           , help="Terminate the script if a file is to be copied onto a folder and vice versa. If not set ignore such cases but print a warning", dest="endOnFileOntoFolder")
parser.add_argument("-G", "--sort-entries"              , action="store_true"           , help="Sort files/folders by name alphabetically before copying. Except for making the logs look more familiar it does not have much other use cases", dest="sortEntries")

parser.add_argument("-m", "--mode", default="copy", choices=MODE_DICT.keys(), type=str.lower, help=f'One of values: {",".join(MODE_DICT.keys())} (Default: copy)')

copyMode = parser.add_argument_group("COPY mode arguments")
copyMode.add_argument("-F", "--force"                   , action="store_true" , help="Force copying of source files even if they are older then destination files", dest="force")
copyMode.add_argument("-N", "--newer-than-newest-file"  , action="store_true" , help="Copy only files newer then the newest file in the destination folder", dest="newerThanNewestFile")
copyMode.add_argument("-M", "--newer-than-newest-folder", action="store_true" , help="Copy only files newer then the newest folder in the destination folder", dest="newerThanNewestFolder")
copyMode.add_argument("-D", "--dont-filter-dest"        , action="store_false", help="Don't filter the destination files/folders WHEN SEARCHING FOR THE NEWEST FILE", dest="filterDest")

# syncMode = parser.add_argument_group("SYNC mode arguments")

args = parser.parse_args()

username               : str                = args.username
hostname               : str                = args.hostname
password               : str                = args.password
localFolder            : str                = args.localFolder
remoteFolder           : str                = args.remoteFolder
inExcludeFiles         : list  [NameFilter] = args.inExcludeFiles
inExcludeFolders       : list  [NameFilter] = args.inExcludeFolders
force                  : bool               = args.force
newerThanNewestFile    : bool               = args.newerThanNewestFile
newerThanNewestFolder  : bool               = args.newerThanNewestFolder
filterDest             : bool               = args.filterDest
maxRecursionDepth      : int                = args.maxRecursionDepth
createMaxRecFolders    : bool               = args.createMaxRecFolders
verbose                : bool               = args.verbose
silent                 : bool               = args.silent
filesNewerThan         : str                = args.filesNewerThan
foldersNewerThan       : str                = args.foldersNewerThan
port                   : int                = args.port
timeout                : float              = args.timeout
preserveTimes          : bool               = args.preserveTimes
preservePermissions    : bool               = args.preservePermissions
dontClose              : bool               = args.dontClose
mode                   : str                = args.mode
createDestFolder       : bool               = args.createDestFolder
fastRemoteListdirAttr  : bool               = args.fastRemoteListdirAttr
listdirAttrFallback    : bool               = args.listdirAttrFallback
endOnInaccessibleEntry : bool               = args.endOnInaccessibleEntry
endOnFileOntoFolder    : bool               = args.endOnFileOntoFolder
sortEntries            : bool               = args.sortEntries
# endregion

# region #* PARAMETER VALIDATION
mode: int = getMode(mode)

if maxRecursionDepth is None: # Argument with no parameter mean no recursion limit
	maxRecursionDepth = sys.maxsize
elif maxRecursionDepth < 0:
	raise SimpleError("-R/--recursive option's parameter cannot be negative")
elif maxRecursionDepth == 0: # -R/--recursive was not specified at all
	if (inExcludeFolders or foldersNewerThan) and not createMaxRecFolders and not silent:
		cprint("Warning: Folder filtering options don't work if -R/--recursive or -x/--create-max-rec-folders was not specified", COLOR_WARN)

if any((username, hostname, password)) and not all((username, hostname, password)):
	raise SimpleError("If any of the parameters -u/--username, -H/--hostname, -p/--password is specified then all of them must be specified")
REMOTE_IS_REMOTE = bool(username)

if silent and verbose:
	raise SimpleError("-s/--silent and -v/--verbose options cannot both be specified at the same time")

localFolder = os.path.abspath(localFolder).replace("\\", "/").rstrip("/")
remoteFolder = remoteFolder.replace("\\", "/").rstrip("/")

dateFormats = (
	"%Y",
	"%Y-%m",
	"%Y-%m-%d",
	"%Y-%m-%d %H",
	"%Y-%m-%d %H:%M",
	"%Y-%m-%d %H:%M:%S",
)
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

# Verifying local folder
if LOCAL_IS_SOURCE or not REMOTE_IS_REMOTE:
	assertFolderExists(sourceFolder)

if not LOCAL_IS_SOURCE or not REMOTE_IS_REMOTE:
	if createDestFolder:
		ensureFolderExists(destFolder)
	else:
		assertFolderExists(destFolder, "\nYou can create it by specifying the -S/--create-dest-folder parameter")

def isFolderCaseSensitiveBase(
	isWindows: bool,
	realFunc: Callable,
	realFuncArgs: tuple,
	folderType: str,
	path: str
) -> tuple[bool, bool]: # errorOccured, caseSense
	if not isWindows:
		return (False, True)

	errorOccured = False
	try:
		caseSense = realFunc(*realFuncArgs)
	except Exception as e:
		errorOccured = True
		if not silent:
			cprint(f'Error occured when determining if {folderType} folder {f'"{path}"' if not verbose else ""} is case-sensitive:\n{e}', COLOR_ERROR)
		caseSense = False # Good assumption as this is the default on windows

	return (errorOccured, caseSense)

if REMOTE_IS_REMOTE: # remoteFolder REALLY refers to a REMOTE folder
	ssh = getSSH(username, hostname, password, timeout, port, silent)
	sftp = ssh.open_sftp()

	# Verifying remote folder
	if LOCAL_IS_SOURCE:
		if createDestFolder:
			ensureRemoteFolderExists(sftp, destFolder)
		else:
			assertRemoteFolderExists(sftp, destFolder, "\nYou can create it by specifying the -S/--create-dest-folder parameter")
	else:
		assertRemoteFolderExists(sftp, sourceFolder)

	def remoteMkdir(path): return remoteMkdirBase(sftp, path)

	if fastRemoteListdirAttr and (pythonStr := remoteHasPython(ssh, throwOnNotFound = not listdirAttrFallback)): # don't throw if listdirAttrFallback
		# it's only noticeably faster if one of the remote folders that will be scanned has more than 5000 entries
		rld = RemoteListDir(ssh, pythonStr, init=False) # don't init the remote python script because remote_listdir_attr might not get called at all
		remote_listdir_attr = rld.listdir_attr
	else:
		if verbose and fastRemoteListdirAttr and not pythonStr:
			cprint('Warning: remote host does not have python. Falling back to "slow" listdir-attr', COLOR_WARN)
		def remote_listdir_attr(path: str): return tuple(sftp.listdir_iter(path)) # this is faster than sftp.listdir_attr because listdir_iter is async

	if LOCAL_IS_SOURCE:
		sourceFolderIter = local_listdir_attr
		destFolderIter = remote_listdir_attr

		sourceMkdir = localMkdir
		destMkdir = remoteMkdir

		sourceUtime = os.utime
		destUtime = sftp.utime

		sourceChmod = os.chmod
		destChmod = sftp.chmod

		copySourceDest = sftp.put
		copyDestSource = sftp.get

		sourceRemove = os.remove
		destRemove = sftp.remove

		sourceRmdir = os.rmdir
		destRmdir = sftp.rmdir

		sourceIsWindows = WINDOWS
		destIsWindows = remoteIsWindows(ssh)

		# Only for Windows
		def isSourceFolderCaseSensitive(path: str): return isFolderCaseSensitiveBase(sourceIsWindows, isLocalFolderCaseSensitive , (path, False), SOURCE_STR, path)
		def isDestFolderCaseSensitive  (path: str): return isFolderCaseSensitiveBase(destIsWindows  , isRemoteFolderCaseSensitive, (ssh , path ), DEST_STR  , path)
	else:
		sourceFolderIter = remote_listdir_attr
		destFolderIter = local_listdir_attr

		sourceMkdir = remoteMkdir
		destMkdir = localMkdir

		sourceUtime = sftp.utime
		destUtime = os.utime

		sourceChmod = sftp.chmod
		destChmod = os.chmod

		copySourceDest = sftp.get
		copyDestSource = sftp.put

		sourceRemove = sftp.remove
		destRemove = os.remove

		sourceRmdir = sftp.rmdir
		destRmdir = os.rmdir

		sourceIsWindows = remoteIsWindows(ssh)
		destIsWindows = WINDOWS

		def isSourceFolderCaseSensitive(path: str): return isFolderCaseSensitiveBase(sourceIsWindows, isRemoteFolderCaseSensitive, (ssh , path ), SOURCE_STR, path)
		def isDestFolderCaseSensitive  (path: str): return isFolderCaseSensitiveBase(destIsWindows  , isLocalFolderCaseSensitive , (path, False), DEST_STR  , path)
else: # remoteFolder ACTUALLY refers to a LOCAL folder
	sourceFolderIter = local_listdir_attr
	destFolderIter   = local_listdir_attr

	sourceMkdir = localMkdir
	destMkdir   = localMkdir

	sourceUtime = os.utime
	destUtime   = os.utime

	sourceChmod = os.chmod
	destChmod   = os.chmod

	copySourceDest = shutil.copyfile
	copyDestSource = shutil.copyfile

	sourceRemove = os.remove
	destRemove   = os.remove

	sourceRmdir = os.rmdir
	destRmdir   = os.rmdir

	sourceIsWindows = WINDOWS
	destIsWindows   = WINDOWS

	def isSourceFolderCaseSensitive(path: str): return isFolderCaseSensitiveBase(sourceIsWindows, isLocalFolderCaseSensitive, (path, False), SOURCE_STR, path)
	def isDestFolderCaseSensitive  (path: str): return isFolderCaseSensitiveBase(destIsWindows  , isLocalFolderCaseSensitive, (path, False), DEST_STR  , path)

SOURCE_DESIGNATION =  "local"  if LOCAL_IS_SOURCE  else ("remote" if REMOTE_IS_REMOTE else "local")
DEST_DESIGNATION   = ("remote" if REMOTE_IS_REMOTE else  "local") if LOCAL_IS_SOURCE  else "local"
SOURCE_DESIGNATION_PADDED = SOURCE_DESIGNATION.ljust(max(len(SOURCE_DESIGNATION), len(DEST_DESIGNATION)))
DEST_DESIGNATION_PADDED   = DEST_DESIGNATION  .ljust(max(len(SOURCE_DESIGNATION), len(DEST_DESIGNATION)))
ENTERING_OK = clr("Entering", COLOR_OK)

class MyNamespace:
	def __init__(self,
		sourceFolderIter,
		destFolderIter,
		sourceMkdir,
		destMkdir,
		sourceUtime,
		destUtime,
		sourceChmod,
		destChmod,
		copySourceDest,
		copyDestSource,
		sourceRemove,
		destRemove,
		sourceRmdir,
		destRmdir,
		sourceIsWindows,
		destIsWindows,
		isSourceFolderCaseSensitive,
		isDestFolderCaseSensitive,
		source_designation,
		dest_designation,
		source_designation_padded,
		dest_designation_padded,
		source_str,
		dest_str,
		sourceFolderBase,
		destFolderBase,
	):
		self.sourceFolderIter            : Callable = sourceFolderIter
		self.destFolderIter              : Callable = destFolderIter
		self.sourceMkdir                 : Callable = sourceMkdir
		self.destMkdir                   : Callable = destMkdir
		self.sourceUtime                 : Callable = sourceUtime
		self.destUtime                   : Callable = destUtime
		self.sourceChmod                 : Callable = sourceChmod
		self.destChmod                   : Callable = destChmod
		self.copySourceDest              : Callable = copySourceDest
		self.copyDestSource              : Callable = copyDestSource
		self.sourceRemove                : Callable = sourceRemove
		self.destRemove                  : Callable = destRemove
		self.sourceRmdir                 : Callable = sourceRmdir
		self.destRmdir                   : Callable = destRmdir
		self.sourceIsWindows             : Callable = sourceIsWindows
		self.destIsWindows               : Callable = destIsWindows
		self.isSourceFolderCaseSensitive : Callable = isSourceFolderCaseSensitive
		self.isDestFolderCaseSensitive   : Callable = isDestFolderCaseSensitive
		self.source_designation          : str = source_designation
		self.dest_designation            : str = dest_designation
		self.source_designation_padded   : str = source_designation_padded
		self.dest_designation_padded     : str = dest_designation_padded
		self.source_str                  : str = source_str
		self.dest_str                    : str = dest_str
		self.sourceFolderBase            : str = sourceFolderBase
		self.destFolderBase              : str = destFolderBase

normalNS = MyNamespace(
	sourceFolderIter            = sourceFolderIter,
	destFolderIter              = destFolderIter,
	sourceMkdir                 = sourceMkdir,
	destMkdir                   = destMkdir,
	sourceUtime                 = sourceUtime,
	destUtime                   = destUtime,
	sourceChmod                 = sourceChmod,
	destChmod                   = destChmod,
	copySourceDest              = copySourceDest,
	copyDestSource              = copyDestSource,
	sourceRemove                = sourceRemove,
	destRemove                  = destRemove,
	sourceRmdir                 = sourceRmdir,
	destRmdir                   = destRmdir,
	sourceIsWindows             = sourceIsWindows,
	destIsWindows               = destIsWindows,
	isSourceFolderCaseSensitive = isSourceFolderCaseSensitive,
	isDestFolderCaseSensitive   = isDestFolderCaseSensitive,
	source_designation          = SOURCE_DESIGNATION,
	dest_designation            = DEST_DESIGNATION,
	source_designation_padded   = SOURCE_DESIGNATION_PADDED,
	dest_designation_padded     = DEST_DESIGNATION_PADDED,
	source_str                  = SOURCE_STR,
	dest_str                    = DEST_STR,
	sourceFolderBase            = sourceFolder,
	destFolderBase              = destFolder,
)
reverseNS = MyNamespace(
	sourceFolderIter            = destFolderIter,
	destFolderIter              = sourceFolderIter,
	sourceMkdir                 = destMkdir,
	destMkdir                   = sourceMkdir,
	sourceUtime                 = destUtime,
	destUtime                   = sourceUtime,
	sourceChmod                 = destChmod,
	destChmod                   = sourceChmod,
	copySourceDest              = copyDestSource,
	copyDestSource              = copySourceDest,
	sourceRemove                = destRemove,
	destRemove                  = sourceRemove,
	sourceRmdir                 = destRmdir,
	destRmdir                   = sourceRmdir,
	sourceIsWindows             = destIsWindows,
	destIsWindows               = sourceIsWindows,
	isSourceFolderCaseSensitive = isDestFolderCaseSensitive,
	isDestFolderCaseSensitive   = isSourceFolderCaseSensitive,
	source_designation          = DEST_DESIGNATION,
	dest_designation            = SOURCE_DESIGNATION,
	source_designation_padded   = DEST_DESIGNATION_PADDED,
	dest_designation_padded     = SOURCE_DESIGNATION_PADDED,
	source_str                  = DEST_STR,
	dest_str                    = SOURCE_STR,
	sourceFolderBase            = destFolder,
	destFolderBase              = sourceFolder,
)

DEST_FILTER_WARN = verbose and filterDest and any(filter(lambda f: f.matchingFunc is fnmatchcase, inExcludeFiles + inExcludeFolders))

# Preserving permissions is only sensible when copying files between Unix machines as Windows has
# different permission system, incompatible with Unix
preservePermissions = preservePermissions and not sourceIsWindows and not destIsWindows
# endregion

# region #* FILE COPYING
REMOVE_COLOR = COLOR_EMPHASIS
def recursiveRemove(
	folderPath: str,
	entry: paramiko.SFTPAttributes,
	iterFun: Callable,
	removeFileFun: Callable,
	removeFolderFun: Callable,
	designation: str,
	type: str,
):
	basePath = posixpath.join(folderPath, entry.filename)
	if isFile(entry):
		try:
			removeFileFun(basePath)
			if not silent:
				cprint(f"Removed: {basePath}", REMOVE_COLOR)
		except Exception as e:
			permissionErrorHandler(e, designation, type, basePath, "file", "deleting")
	elif isDir(entry):
		try:
			entries = iterFun(basePath)
		except Exception as e:
			permissionErrorHandler(e, designation, type, basePath)
			return

		for entry in entries:
			newPath = posixpath.join(folderPath, entry.filename)
			if isFile(entry):
				try:
					removeFileFun(newPath)
					if not silent:
						cprint(f"Removed: {newPath}", REMOVE_COLOR)
				except Exception as e:
					permissionErrorHandler(e, designation, type, basePath, "file", "deleting")
			elif isDir(entry):
				recursiveRemove(newPath, entry, iterFun, removeFileFun, removeFolderFun)

		try:
			removeFolderFun(basePath)
			if not silent:
				cprint(f"Removed: {basePath}", REMOVE_COLOR)
		except Exception as e:
			permissionErrorHandler(e, designation, type, basePath, "folder", "deleting")

def fileOnFolderErrorHandler(entry: paramiko.SFTPAttributes):
	txt = f'Warning: tried copying a {'file' if isFile(entry) else 'folder'} onto a {'folder' if isFile(entry) else 'file'} with a name "{entry.filename}"'
	if endOnFileOntoFolder:
		raise SimpleError(txt)
	else:
		if not silent:
			cprint(txt, COLOR_WARN)

def permissionErrorHandler(err: Exception, designation: str, type: str, path: str, fileFolder = "folder", operation = "listing"):
	# This is not the best way to correctly identify permission errors but it needs to be this way
	# because of inconsistencies in OSes and SSH server implementations. On Windows running OpenSSH I
	# observed that when logged as non admin and trying to listdir admin's folder the server returns
	# "Bad message" text. On Termux on Android running OpenSSH when listdir'ing the root folder "/"
	# the server returns "Failure" text. I think the servers should return the SFTP_PERMISSION_DENIED
	# error code so the error could be casted to PermissionError by paramiko but it is what it is...
	if err is PermissionError or (err is IOError and (errorMsg := str(err)) and (errorMsg == "Failure" or errorMsg == "Bad message")):
		txt = f'Warning: permission denied when {operation} the {designation} {type} {fileFolder} "{path}"'
		if endOnInaccessibleEntry:
			raise SimpleError(txt)
		else:
			if not silent:
				cprint(txt, COLOR_WARN)
	else:
		raise err

def innerFilterFun(entry: paramiko.SFTPAttributes) -> bool:
	# ___NewerThanDate comparisons use the < operator so if the user inputs exact modification date
	# of some file/folder that file/folder will not be included in the operations
	return isDir (entry) and foldersNewerThanDate < entry.st_mtime and folderMatch(entry.filename) \
	    or isFile(entry) and filesNewerThanDate   < entry.st_mtime and fileMatch  (entry.filename)

if verbose:
	class FilterClass:
		def __init__(self, sourceFolderParam, sourceFolderBase):
			self.sourceFolderParam = sourceFolderParam
			self.sourceFolderBase = sourceFolderBase
		def __call__(self, entry: paramiko.SFTPAttributes) -> bool:
			val = innerFilterFun(entry)

			if not val:
				name = entry.filename
				relPath = posixpath.join(self.sourceFolderParam, name).replace(self.sourceFolderBase, "", count=1)
				if isDir(entry):
					if not (foldersNewerThanDate <= entry.st_mtime):
						print(f'{relPath} - skipping because it ({modifiedDate(entry)}) is not newer than -f/--folders-newer-than parameter')
					elif not folderMatch(name):
						print(f"{relPath} - skipping because folderMatch returned False")
					else:
						cprint(f"{relPath} - skipping file because of unknown reason", COLOR_ERROR) # Shouldn't happen
				elif isFile(entry):
					if not (filesNewerThanDate <= entry.st_mtime):
						print(f'{relPath} - skipping because it ({modifiedDate(entry)}) is not newer than -n/--files-newer-than parameter')
					elif not fileMatch(name):
						print(f"{relPath} - skipping because fileMatch returned False")
					else:
						cprint(f"{relPath} - skipping file because of unknown reason", COLOR_ERROR) # Shouldn't happen
				else:
					print(f"{relPath} - skipping because it is not a file nor folder")

			return val

def checkCaseDuplicates(
	entriesList: list[paramiko.SFTPAttributes],
	sourceErrorOccured: bool,
	destErrorOccured: bool,
	designation: str,
	type: str,
	path: str
) -> list[paramiko.SFTPAttributes]:
	""" Check for case-insensitive filename duplicates and exclude them from copy/sync operations """
	caselessEntries = defaultdict(list)
	for entry in entriesList:
		caselessEntries[entry.filename.lower()].append(entry)

	caseDuplicates: list[list[paramiko.SFTPAttributes]] = []
	for entries in caselessEntries.values():
		if len(entries) > 1:
			caseDuplicates.append(entries)

	if caseDuplicates:
		if not silent:
			print(f'Following files/folders in the {designation} {type} folder "{path}" have names that only differ in letter case:')
			for i, entries in enumerate(caseDuplicates, start=1):
				print(f"Group {i}:")
				for entry in entries:
					print(entry.filename)
			cprint(f"And they will not be copied unless you change their names or enable case-sensitivity in the destination Windows folder with fsutil.exe", COLOR_WARN)
		caseDuplicatesFlattened = tuple(chain.from_iterable(caseDuplicates))
		entriesList = tuple(filter(lambda e: e not in caseDuplicatesFlattened, entriesList))
	elif sourceErrorOccured or destErrorOccured:
		if not silent:
			cprint(f"...but it won't cause any problems because {designation} {type} files/folders are case-sensitivly unique", COLOR_OK)

	return entriesList

def recursiveCopyHelper(
	sourceEntry: paramiko.SFTPAttributes,
	sourceFolderParam: str,
	destEntry: paramiko.SFTPAttributes,
	destFolderParam: str,
	depth: int,
	NNS: MyNamespace,
	RNS: MyNamespace,
	force: bool = False,
	newestDestDate: int = 0,
) -> ACTION:
	# In the following code posixpath.join is used correctly with case-sensitive name because:
	#    1. Windows accepts forward slashes "/" as path separators
	#    2. Windows paths are case-insensitive but case preserving so it will normalize the path before accessing the FS
	sourceName = sourceEntry.filename
	destName = destEntry.filename if destEntry else sourceName

	if not silent or verbose:
		relPath = posixpath.join(sourceFolderParam, sourceName).replace(NNS.sourceFolderBase, "", count=1)

	if isFile(sourceEntry) and newestDestDate < sourceEntry.st_mtime:
		if destEntry and isDir(destEntry):
			fileOnFolderErrorHandler(sourceEntry)
			return ACTION.CONTINUE # because in MODE.SYNC next function call would raise the same exception

		if force or not destEntry or destEntry.st_mtime < sourceEntry.st_mtime:
			sourcePath = posixpath.join(sourceFolderParam, sourceName)
			destPath   = posixpath.join(destFolderParam  , destName  )

			if not silent:
				if mode == MODE.SYNC:
					cprint(f"{relPath} - {'source -> destination' if NNS is normalNS else 'destination -> source'}", COLOR_OK)
				else: # MODE.COPY
					cprint(relPath, COLOR_OK)

			try:
				NNS.copySourceDest(sourcePath, destPath)
			except Exception as e:
				permissionErrorHandler(e, NNS.dest_designation, NNS.dest_str, destPath)
				return ACTION.RETURN # because every next file would raise the same exception

			if preserveTimes:
				NNS.destUtime(destPath, (sourceEntry.st_atime, sourceEntry.st_mtime))

			if preservePermissions and (not destEntry or sourceEntry.st_mode != destEntry.st_mode):
				NNS.destChmod(destPath, sourceEntry.st_mode)
		elif verbose:
			if not (destEntry.st_mtime < sourceEntry.st_mtime):
				print(f"{relPath} - skipping file because it is not newer than the {NNS.dest_str}")
			else:
				cprint(f"{relPath} - skipping file because of unknown reason", COLOR_ERROR) # Shouldn't happen
	elif isDir(sourceEntry) and (depth < maxRecursionDepth or createMaxRecFolders):
		if destEntry and isFile(destEntry):
			fileOnFolderErrorHandler(sourceEntry)
			return ACTION.CONTINUE

		newDestFolder = posixpath.join(destFolderParam, destName)
		if not destEntry:
			NNS.destMkdir(newDestFolder)

		if preservePermissions and (not destEntry or sourceEntry.st_mode != destEntry.st_mode):
			NNS.destChmod(newDestFolder, sourceEntry.st_mode)

		if depth < maxRecursionDepth:
			newSourceFolder = posixpath.join(sourceFolderParam, sourceName)
			recursiveCopy(
				sourceFolderParam = newSourceFolder,
				destFolderParam   = newDestFolder,
				NNS = NNS,
				RNS = RNS,
				depth = depth + 1,
			)

		if preserveTimes: # We cannot set the time conditionally as putting any files inside the folder updated it modification date
			NNS.destUtime(newDestFolder, (sourceEntry.st_atime, sourceEntry.st_mtime))

		return ACTION.CONTINUE # so te recursion doesn't happen on the next function call
	elif verbose:
		if isFile(sourceEntry):
			if not (newestDestDate < sourceEntry.st_mtime):
				print(f"{relPath} - skipping file because it ({modifiedDate(sourceEntry)}) is not newer than newestDestDate")
			else:
				cprint(f"{relPath} - skipping file because of unknown reason", COLOR_ERROR) # Shouldn't happen
		elif isDir(sourceEntry):
			if not (depth < maxRecursionDepth or createMaxRecFolders):
				print(f"{relPath} - skipping folder because it we are at max recursion depth and createMaxRecFolders is False")
			else:
				cprint(f"{relPath} - skipping file because of unknown reason", COLOR_ERROR) # Shouldn't happen

	return ACTION.NONE

def recursiveCopy(
	sourceFolderParam: str,
	destFolderParam: str,
	NNS: MyNamespace,
	RNS: MyNamespace,
	depth: int = 0
):
	if verbose:
		print(f"{ENTERING_OK} {NNS.source_designation_padded} source      folder: {sourceFolderParam}")
		print(f"{ENTERING_OK} {NNS.dest_designation_padded  } destination folder: {destFolderParam}")
		filterFun = FilterClass(sourceFolderParam, NNS.sourceFolderBase)
	else:
		filterFun = innerFilterFun

	match mode:
		case MODE.COPY:
			try:
				sourceEntries: tuple[paramiko.SFTPAttributes] = tuple(filter(filterFun, NNS.sourceFolderIter(sourceFolderParam)))
			except Exception as e:
				permissionErrorHandler(e, NNS.source_designation, NNS.source_str, sourceFolderParam)
				return

			if not sourceEntries: return

			sourceErrorOccured, sourceCaseSense = NNS.isSourceFolderCaseSensitive(sourceFolderParam)
			destErrorOccured  , destCaseSense   = NNS.isDestFolderCaseSensitive  (destFolderParam  )
			# ANY_CASE_INSENSITIVE = not sourceCaseSense or not destCaseSense

			if sourceCaseSense and not destCaseSense: # Most probable scenario: copy from Linux to Windows
				sourceEntries = checkCaseDuplicates(sourceEntries, sourceErrorOccured, destErrorOccured, NNS.source_designation, NNS.source_str, sourceFolderParam)
				if not sourceEntries: return

			if sortEntries:
				sourceEntries = sorted(sourceEntries, key=lambda x: x.filename)

			try:
				destEntries: list[paramiko.SFTPAttributes] = NNS.destFolderIter(destFolderParam)
			except Exception as e:
				permissionErrorHandler(e, NNS.dest_designation, NNS.dest_str, destFolderParam)
				return

			newestDestDate = 0
			if newerThanNewestFile or newerThanNewestFolder: # find newest file/folder in the destination folder
				if DEST_FILTER_WARN and not destCaseSense:
					cprint("Warning: When searching for newest file in the destination folder you may have excluded some files/folders case-sensitivly but the destination folder is case-insensitive", COLOR_WARN)

				entryCount = 0
				for entry in (filter(innerFilterFun, destEntries) if filterDest else destEntries):
					if newerThanNewestFile and isFile(entry) or newerThanNewestFolder and isDir(entry):
						entryCount += 1
						if newestDestDate < entry.st_mtime:
							newestDestDate = entry.st_mtime

				if verbose:
					matching = " matching" if filterDest else ""
					filesFolders = "files/folders" if newerThanNewestFile and newerThanNewestFolder else ("files" if newerThanNewestFile else "folders")
					theNewest = f"and the newest from them has date {datetime.fromtimestamp(newestDestDate)} -> newestDestDate" if entryCount else ""
					print(f"Destination folder has {entryCount}{matching} {filesFolders} {theNewest}")

			# Explanation for following if staments containing destCaseSense:
			# sourceCaseSense and destCaseSense: (i.e. Linux -> Linux) Both are case-sensitive so no need to normalize case
			# sourceCaseSense and not destCaseSense: (i.e. Linux -> Windows) Case normalization necessary as Windows is case-insensitive
			# not sourceCaseSense and destCaseSense: (i.e. Windows -> Linux) No need to normalize case as case-insensitive names are a subset of case-sensitive names
			# not sourceCaseSense and not destCaseSense: (i.e. Windows -> Windows) Case normalization necessary as both are case-insensitive
			# So we can se that case normalization is only necessary if not destCaseSense
			if destCaseSense:
				destEntriesDict = {entry.filename: entry for entry in destEntries}
			else:
				destEntriesDict = {entry.filename.lower(): entry for entry in destEntries}

			for sourceEntry in sourceEntries:
				name = sourceEntry.filename
				if recursiveCopyHelper(
					sourceEntry       = sourceEntry,
					destEntry         = destEntriesDict.get(name if destCaseSense else name.lower()),
					sourceFolderParam = sourceFolderParam,
					destFolderParam   = destFolderParam,
					depth             = depth,
					NNS               = NNS,
					RNS               = RNS,
					force             = force,
					newestDestDate    = newestDestDate,
				) == ACTION.RETURN: return
		case MODE.SYNC:
			try:
				sourceEntriesBase: list[paramiko.SFTPAttributes] = NNS.sourceFolderIter(sourceFolderParam)
			except Exception as e:
				permissionErrorHandler(e, NNS.source_designation, NNS.source_str, sourceFolderParam)
				return

			try:
				destEntriesBase: list[paramiko.SFTPAttributes] = NNS.destFolderIter(destFolderParam)
			except Exception as e:
				permissionErrorHandler(e, NNS.dest_designation, NNS.dest_str, destFolderParam)
				return

			sourceEntries = tuple(filter(filterFun, sourceEntriesBase))
			destEntries   = tuple(filter(filterFun, destEntriesBase  ))

			if not (sourceEntries or destEntries): return

			sourceErrorOccured, sourceCaseSense = NNS.isSourceFolderCaseSensitive(sourceFolderParam)
			destErrorOccured  , destCaseSense   = NNS.isDestFolderCaseSensitive  (destFolderParam  )

			if not sourceCaseSense or not destCaseSense:
				sourceEntries = checkCaseDuplicates(sourceEntries, sourceErrorOccured, destErrorOccured, NNS.source_designation, NNS.source_str, sourceFolderParam)
				destEntries   = checkCaseDuplicates(destEntries  , sourceErrorOccured, destErrorOccured, NNS.dest_designation  , NNS.dest_str  , destFolderParam  )

				if not (sourceEntries or destEntries): return

				sourceEntriesDictBase = {entry.filename.lower(): entry for entry in sourceEntriesBase}
				destEntriesDictBase   = {entry.filename.lower(): entry for entry in destEntriesBase  }
				sourceEntriesDict     = {entry.filename.lower(): entry for entry in sourceEntries    }
				destEntriesDict       = {entry.filename.lower(): entry for entry in destEntries      }
			else:
				sourceEntriesDictBase = {entry.filename: entry for entry in sourceEntriesBase}
				destEntriesDictBase   = {entry.filename: entry for entry in destEntriesBase  }
				sourceEntriesDict     = {entry.filename: entry for entry in sourceEntries    }
				destEntriesDict       = {entry.filename: entry for entry in destEntries      }

			allNames = sourceEntriesDict.keys() | destEntriesDict.keys()

			if sortEntries:
				allNames = sorted(allNames)

			newestCommonDate = 0
			allEntries: List[Tuple[paramiko.SFTPAttributes, paramiko.SFTPAttributes, str]] = []
			for name in allNames:
				sourceEntry = sourceEntriesDict.get(name)
				destEntry   = destEntriesDict  .get(name)
				allEntries.append((sourceEntry, destEntry, name))
				if sourceEntry and destEntry and sourceEntry.st_mtime == destEntry.st_mtime:
					if newestCommonDate < sourceEntry.st_mtime:
						newestCommonDate = sourceEntry.st_mtime

			for sourceEntry, destEntry, name in allEntries:
				# When sourceEntry is None sourceEntryBase might not be None (because i.e. folders where
				# filetered out). That's why we need to get it from the dict and check it. The same
				# applies to destEntry and destEntryBase.
				# When sourceEntry is not None and sourceEntryBase is not None then they should refer to
				# the same object so sourceEntry is sourceEntryBase == True
				sourceEntryBase = sourceEntriesDictBase.get(name)
				destEntryBase   = destEntriesDictBase  .get(name)

				if sourceEntry:
					if not destEntryBase and sourceEntry.st_mtime < newestCommonDate:
						recursiveRemove(sourceFolderParam, sourceEntry, NNS.sourceFolderIter, NNS.sourceRemove, NNS.sourceRmdir, NNS.source_designation, NNS.source_str)
					else:
						match recursiveCopyHelper(
							sourceEntry       = sourceEntry,
							destEntry         = destEntryBase,
							sourceFolderParam = sourceFolderParam,
							destFolderParam   = destFolderParam,
							depth             = depth,
							NNS               = NNS,
							RNS               = RNS,
						):
							case ACTION.CONTINUE: continue
							case ACTION.RETURN: return
				if destEntry:
					if not sourceEntryBase and destEntry.st_mtime < newestCommonDate:
						recursiveRemove(destFolderParam, destEntry, NNS.destFolderIter, NNS.destRemove, NNS.destRmdir, NNS.dest_designation, NNS.dest_str)
					else:
						match recursiveCopyHelper(
							sourceEntry       = destEntry,
							destEntry         = sourceEntryBase,
							sourceFolderParam = destFolderParam,
							destFolderParam   = sourceFolderParam,
							depth             = depth,
							NNS               = RNS,
							RNS               = NNS,
						):
							case ACTION.CONTINUE: continue
							case ACTION.RETURN: return


if not silent:
	match mode:
		case MODE.COPY: operation = "Copying"
		case MODE.SYNC: operation = "Syncing"

	print(f"{operation} from {SOURCE_DESIGNATION} to {DEST_DESIGNATION}")
	print(f"Source      folder: {sourceFolder}")
	print(f"Destination folder: {destFolder}")
	print(f"{operation} files:\n")

recursiveCopy(
	sourceFolderParam = sourceFolder,
	destFolderParam   = destFolder,
	NNS = normalNS,
	RNS = reverseNS,
	depth = 0,
)

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
		input(clr("\nPress ENTER to continue...", COLOR_OK))
# endregion
