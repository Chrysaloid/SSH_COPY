import sys; from pathlib import Path; p = Path(__file__).resolve().parent; __package__ = p.name; sys.path.append(p.parent.as_posix()) # To be able to use relative imports

from argparse import Namespace
from datetime import datetime
from enum import auto, IntEnum
from fnmatch import fnmatchcase
from functools import partial as bindKwarg
from operator import attrgetter as getAttr, itemgetter as getItem
import os
import shutil
from time import perf_counter
from typing import Callable, Tuple

from termcolor import colored as clr, cprint

from .argparseUtils import ArgumentParser_ColoredError, COMMON_FORMATTER_CLASS
from .fileUtils import assertFolderExists as assertLocalFolderExists, isDir, isFile
from .LocalSFTPAttributes import local_listdir_attr, LocalSFTPAttributes
from .printRelTime import printRelTime
from .SimpleError import SimpleError
from .sshUtils import assertRemoteFolderExists, getSSH, remoteIsWindows, RemoteListDir

"""
Edge cases that were disregarded:
- case-insensitivity of file names on Windows - use `fsutil file setCaseSensitiveInfo "C:/path to folder" enable` to enable case-sensitivity for your folder(s)
- caching of directory listings - while it speeds up the copying process it may result in omitting some files in more complex setups. You can disable it using --cache-directory-listings flag
- this script is supposed to be simple so no recursion is performed
"""

def printReturn(thing):
	print(thing)
	return thing

class PaddedIntEnum(IntEnum):
	def __init_subclass__(cls, **kwargs):
		super().__init_subclass__(**kwargs)

		maxLen = max(len(member.name) for member in cls)

		for member in cls:
			member._padded_name_ = member.name.ljust(maxLen)
			member._name_lower_ = member.name.lower()

	@classmethod
	def parseMember(cls, txt: str):
		txt = txt.lower().strip()

		for member in cls:
			if txt == member._name_lower_ or txt == member._name_lower_[0]:
				return member

		raise SimpleError(f"Invalid {cls.name}: {txt}")

class MODE(PaddedIntEnum):
	SYNC     = auto()
	COPY     = auto()
	DEL_COPY = auto()
	MOVE     = auto()

class PLACE(PaddedIntEnum):
	LOCAL = auto()
	REMOTE = auto()

def parseBool(txt: str, name = "bool") -> bool:
	match txt.lower().strip():
		case "1" | "true" | "t" | "yes" | "yeah" | "yup" | "tak" | "on": return True
		case "0" | "false" | "f" | "no" | "nah" | "nope" | "nie" | "off": return False
		case _: raise SimpleError(f"Invalid {name}: {txt}")

def parseFilePattern(txt: str):
	filePattern, filePatternBool = txt.split("/", 1)
	return (filePattern, parseBool(filePatternBool, "filePatternBool"))

class CallAccumulator:
	def __init__( self, ) -> None:
		self.args = []

	def __call__(self, *args) -> None:
		self.args.append(args)
		return self

	def __repr__(self):
		return f"CallAccumulator(calls={self.args})"

def filterFun(file: LocalSFTPAttributes, filePatterns: Tuple[Tuple[str, bool], ...], defaultMatch: bool) -> bool:
	if isDir(file): return False # this script is supposed to be simple so no recursion is performed

	for pattern, matchVal in filePatterns:
		if fnmatchcase(file.filename, pattern):
			return matchVal

	return defaultMatch

def normalizeLocalFolderPath(localFolder: str) -> str:
	return os.path.abspath(localFolder).replace("\\", "/").rstrip("/") + "/"

def normalizeRemoteFolderPath(remoteFolder: str) -> str:
	return remoteFolder.replace("\\", "/").rstrip("/") + "/"

def pathJoin(folder, file):
	return folder + file

magentaSource = clr("Source", "magenta")
cyanDest = clr("Dest", "cyan")
magentaS = clr("S", "magenta")
cyanD = clr("D", "cyan")

blueColor = "light_blue"

def main(args: Namespace = None):
	start = perf_counter()

	argsFromCli = not bool(args)

	if argsFromCli:
		parser = ArgumentParser_ColoredError(
			description="Copy, move or sync files between folders on remote or local machines",
			formatter_class=COMMON_FORMATTER_CLASS,
		)

		required = parser.add_argument_group("Required arguments")
		parser._action_groups = [required, parser._optionals]

		required.add_argument(
			"-o",
			"--operation",
			required=True,
			action="append",
			nargs=7,
			metavar=(
				"SOURCE_DIR",
				"SOURCE_PLACE",
				"DEST_DIR",
				"DEST_PLACE",
				"MODE",
				"FILE_PATTERNS",
				"DEFAULT_MATCH"
			),
			help="Operation to perform. Can be specified multiple times",
			dest="operations",
		)
		required.add_argument("-u", "--username", required=True, default="", help="Remote username")
		required.add_argument("-H", "--hostname", required=True, default="", nargs="+", help="Remote host's address. You can specify multiple if host can appear under multiple adresses")

		parser._optionals.title = "Optional arguments"

		parser.add_argument("-p", "--password"                , default=None         , help="Remote password")
		parser.add_argument("-P", "--port"                    , default=22, type=int , help="Remote port (default: 22)")
		parser.add_argument("-T", "--timeout"                 , default=5, type=float, help="TCP 3-way handshake timeout in seconds (default: 5.0)", metavar="SECONDS")
		parser.add_argument("-v", "--verbose"                 , action="store_true"  , help="Print verbose information. Good for debugging")
		parser.add_argument("-s", "--silent"                  , action="store_true"  , help="Print only errors")
		parser.add_argument("-d", "--dry-run"                 , action="store_true"  , help="Do not perform any copying and just print the information that would normally be printed. Good for testing", dest="dryRun")
		parser.add_argument("-O", "--remote-os"               , default="auto"       , help="Remote host's operating system. Can be (a, auto, auto-detect) or (w, win, windows) or (u, unix, l, linux, p, posix, m, macos). Windows just needs to be handled in a special way so we need to differentiate it from the others. Auto will run a few commands on the remote machine to determine it's OS and they are not 100%% relaible so if you know the remote's OS and want to save time you can use this argument (default: auto)", dest="remoteOs")
		parser.add_argument("-c", "--cache-directory-listings", action="store_true"  , help="Listing all entries in a directory is a bit expensive operation so caching speeds up the copying process but it may result in omitting some files in more complex setups (i.e. for folders [A: 1 file, B: empty, C: empty] and operations ['copy from A to B', 'copy from B to C'] running the script would result in folder C still being empty because cached empty listing of folder B would be used in the second operation). To reduce confusion the caching is disabled by default and you have to enable it using this flag", dest="cacheDirectoryListings")

		args = parser.parse_args()

	operations             : list  [list[str]] = args.operations
	username               : str               = args.username
	hostname               : str               = args.hostname
	password               : str               = args.password
	port                   : int               = args.port
	timeout                : float             = args.timeout
	verbose                : bool              = args.verbose
	silent                 : bool              = args.silent
	dryRun                 : bool              = args.dryRun
	remoteOs               : str               = args.remoteOs
	cacheDirectoryListings : bool              = args.cacheDirectoryListings

	if silent and verbose:
		raise SimpleError("-s/--silent and -v/--verbose options cannot both be specified at the same time")

	if argsFromCli:
		parsedOperations = []
		for sourceDir, sourcePlace, destDir, destPlace, mode, filePatterns, defaultMatch in operations:
			sourcePlace  = PLACE.parseMember(sourcePlace)
			destPlace    = PLACE.parseMember(destPlace)
			if sourcePlace == PLACE.LOCAL: assertLocalFolderExists(sourceDir)
			if destPlace   == PLACE.LOCAL: assertLocalFolderExists(destDir)
			mode         = MODE.parseMember(mode)
			filePatterns = tuple(map(parseFilePattern, filePatterns.split("|"))) if filePatterns else []
			defaultMatch = parseBool(defaultMatch, "defaultMatch")
			parsedOperations.append((sourceDir, sourcePlace, destDir, destPlace, mode, filePatterns, defaultMatch))
	else:
		parsedOperations = operations

	ssh, thereWasSSHError = getSSH(
		username  = username,
		hostnames = hostname,
		password  = password,
		timeout   = timeout ,
		port      = port    ,
		silent    = silent  ,
	)
	sftp = ssh.open_sftp()

	match remoteOs.lower().strip():
		case "w" | "win" | "windows": REMOTE_IS_WINDOWS = True
		case "u" | "unix" | "l" | "linux" | "p" | "posix" | "m" | "macos": REMOTE_IS_WINDOWS = False
		case "a" | "auto" | "auto-detect": REMOTE_IS_WINDOWS = remoteIsWindows(ssh)
		case _: raise SimpleError(f"Invalid OS: {remoteOs}")

	if verbose: print(f"Remote OS is {"Windows" if REMOTE_IS_WINDOWS else "not Windows"}")

	class RemoteCopyBatch:
		def __init__(
			self,
			sourceDir: str,
			destDir: str,
			command: str,
			printFiles = False,
			printColor = "green",
		) -> None:
			self.files: list[str] = []
			self.sourceDir = sourceDir
			self.destDir = destDir
			self.command = command
			self.printFiles = printFiles
			self.printColor = printColor

		def __call__(self, filename: str, _) -> None:
			self.files.append(filename)

		def finalize(self) -> None:
			if not self.files:
				return

			if not dryRun:
				stdin, stdout, stderr = ssh.exec_command(f'cd {"/d" if REMOTE_IS_WINDOWS else ""} "{self.sourceDir}" && xargs -0 {self.command} -t "{self.destDir}"')

				if self.printFiles and not silent and not isinstance(self.files, (list, tuple)): # nenecessary because self.files might be an iterable
					self.files = tuple(self.files)

				stdin.write("\0".join(self.files).replace(self.destDir, "") + "\0")
				stdin.channel.shutdown_write()

				exitCode = stdout.channel.recv_exit_status()

				if exitCode != 0:
					raise RuntimeError(f"Remote copy failed:\n{stdout.read().decode()}\n{stderr.read().decode()}")

			if self.printFiles and not silent:
				cprint("\n".join(self.files), self.printColor)

	def filterFun(file: LocalSFTPAttributes, filePatterns: Tuple[Tuple[str, bool], ...], defaultMatch: bool) -> bool:
		if isDir(file): return False # this script is supposed to be simple so no recursion is performed

		for pattern, matchVal in filePatterns:
			if fnmatchcase(file.filename, pattern):
				return matchVal

		return defaultMatch

	def syncFun(sourceFiles: dict[str, LocalSFTPAttributes], sourcePlace: PLACE, destFiles: dict[str, LocalSFTPAttributes], destPlace: PLACE, sourceDir: str, destDir: str):
		if sourcePlace == PLACE.LOCAL and destPlace == PLACE.LOCAL:
			copySourceDest = bindKwarg(shutil.copyfile, follow_symlinks=False)
			copyDestSource = copySourceDest
			utimeDest      = os.utime
			utimeSource    = os.utime
			removeDest     = os.remove
			removeSource   = os.remove
		elif sourcePlace == PLACE.REMOTE and destPlace == PLACE.LOCAL:
			copySourceDest = sftp.get
			copyDestSource = bindKwarg(sftp.put, confirm=False)
			utimeDest      = os.utime
			utimeSource    = sftp.utime
			removeDest     = os.remove
			removeSource   = sftp.remove
		elif sourcePlace == PLACE.LOCAL and destPlace == PLACE.REMOTE:
			copySourceDest = bindKwarg(sftp.put, confirm=False)
			copyDestSource = sftp.get
			utimeDest      = sftp.utime
			utimeSource    = os.utime
			removeDest     = sftp.remove
			removeSource   = os.remove
		elif sourcePlace == PLACE.REMOTE and destPlace == PLACE.REMOTE:
			copySourceDest = RemoteCopyBatch(sourceDir, destDir, "cp -u", False)
			copyDestSource = RemoteCopyBatch(destDir, sourceDir, "cp -u", False)
			utimeDest      = CallAccumulator()
			utimeSource    = CallAccumulator()
			removeDest     = sftp.remove
			removeSource   = sftp.remove

		newestCommonDate = 0 # start from smallest (reasonably) possible date
		for filename in sourceFiles.keys() & destFiles.keys(): # common keys
			sourceFile = sourceFiles[filename]
			if newestCommonDate < sourceFile.st_mtime and sourceFile.st_mtime == destFiles[filename].st_mtime:
				newestCommonDate = sourceFile.st_mtime

		if not silent:
			print(f"""# Newest common date: {
				datetime.fromtimestamp(newestCommonDate)
				.strftime('%Y-%m-%d %H:%M:%S - {rel}')
				.format(rel = printRelTime(newestCommonDate)) if newestCommonDate else clr("None because there are no common files", "yellow")
			}""")

		for filename in sourceFiles.keys() | destFiles.keys(): # all keys
			sourceFile = sourceFiles.get(filename)
			destFile   = destFiles  .get(filename)

			if sourceFile and destFile:
				if sourceFile.st_mtime > destFile.st_mtime:                                 # Case 1
					if not silent: print(f"{magentaS} -> {cyanD}: {clr(filename, "green")}")
					if not dryRun:
						sPath = pathJoin(sourceDir, filename)
						dPath = pathJoin(destDir  , filename)
						copySourceDest(sPath, dPath)
						utimeDest(dPath, (sourceFile.st_atime, sourceFile.st_mtime))
				elif sourceFile.st_mtime < destFile.st_mtime:                               # Case 2
					if not silent: print(f"{cyanD} -> {magentaS}: {clr(filename, "green")}")
					if not dryRun:
						sPath = pathJoin(sourceDir, filename)
						dPath = pathJoin(destDir  , filename)
						copyDestSource(dPath, sPath)
						utimeSource(sPath, (destFile.st_atime, destFile.st_mtime))
			elif sourceFile:
				if sourceFile.st_mtime >= newestCommonDate:                                 # Case 1
					if not silent: print(f"{magentaS} -> {cyanD}: {clr(filename, "green")}")
					if not dryRun:
						sPath = pathJoin(sourceDir, filename)
						dPath = pathJoin(destDir  , filename)
						copySourceDest(sPath, dPath)
						utimeDest(dPath, (sourceFile.st_atime, sourceFile.st_mtime))
				else:                                                                       # Case 3
					if not silent: print(f"{magentaS}: {clr(filename, "red")}")
					if not dryRun:
						sPath = pathJoin(sourceDir, filename)
						removeSource(sPath)
			elif destFile:
				if destFile.st_mtime >= newestCommonDate:                                   # Case 2
					if not silent: print(f"{cyanD} -> {magentaS}: {clr(filename, "green")}")
					if not dryRun:
						sPath = pathJoin(sourceDir, filename)
						dPath = pathJoin(destDir  , filename)
						copyDestSource(dPath, sPath)
						utimeSource(sPath, (destFile.st_atime, destFile.st_mtime))
				else:                                                                       # Case 4
					if not silent: print(f"{cyanD}: {clr(filename, "red")}")
					if not dryRun:
						dPath = pathJoin(destDir  , filename)
						removeDest(dPath)

			# # Alternative logic
			# if (sourceFile and destFile and sourceFile.st_mtime > destFile.st_mtime) or (sourceFile and not destFile and sourceFile.st_mtime >= newestCommonDate): # Case 1
			# 	if not silent: print(f"{magentaS} -> {cyanD}: {clr(filename, "green")}")
			# 	sPath = pathJoin(sourceDir, filename)
			# 	dPath = pathJoin(destDir  , filename)
			# 	copySourceDest(sPath, dPath)
			# 	utimeDest(dPath, (sourceFile.st_atime, sourceFile.st_mtime))
			# elif (sourceFile and destFile and sourceFile.st_mtime < destFile.st_mtime) or (not sourceFile and destFile and destFile.st_mtime >= newestCommonDate): # Case 2
			# 	if not silent: print(f"{cyanD} -> {magentaS}: {clr(filename, "green")}")
			# 	sPath = pathJoin(sourceDir, filename)
			# 	dPath = pathJoin(destDir  , filename)
			# 	copyDestSource(dPath, sPath)
			# 	utimeSource(sPath, (destFile.st_atime, destFile.st_mtime))
			# elif sourceFile and not destFile and sourceFile.st_mtime < newestCommonDate:                                                                           # Case 3
			# 	if not silent: print(f"{magentaS}: {clr(filename, "yellow")}")
			# 	sPath = pathJoin(sourceDir, filename)
			# 	removeSource(sPath)
			# elif not sourceFile and destFile and destFile.st_mtime < newestCommonDate:                                                                             # Case 4
			# 	if not silent: print(f"{cyanD}: {clr(filename, "yellow")}")
			# 	dPath = pathJoin(destDir  , filename)
			# 	removeDest(dPath)

		if sourcePlace == PLACE.REMOTE and destPlace == PLACE.REMOTE and not dryRun:
			copySourceDest.finalize()
			copyDestSource.finalize()
			for path, times in utimeDest  .args: sftp.utime(path, times)
			for path, times in utimeSource.args: sftp.utime(path, times)

	def copyFun(sourceFiles: list[LocalSFTPAttributes], sourcePlace: PLACE, destFiles: dict[str, LocalSFTPAttributes], destPlace: PLACE, sourceDir: str, destDir: str):
		if sourcePlace == PLACE.LOCAL and destPlace == PLACE.LOCAL:
			copy = bindKwarg(shutil.copyfile, follow_symlinks=False)
			utime = os.utime
		elif sourcePlace == PLACE.REMOTE and destPlace == PLACE.LOCAL:
			copy = sftp.get
			utime = os.utime
		elif sourcePlace == PLACE.LOCAL and destPlace == PLACE.REMOTE:
			copy = bindKwarg(sftp.put, confirm=False)
			utime = sftp.utime
		elif sourcePlace == PLACE.REMOTE and destPlace == PLACE.REMOTE:
			copy = RemoteCopyBatch(sourceDir, destDir, "cp -u", True)
			copy.files = map(getAttr("filename"), sourceFiles)
			copy.finalize()
			return

		for file in sourceFiles:
			destFile = destFiles.get(file.filename)
			if destFile and destFile.st_mtime >= file.st_mtime: continue # destination exists and is newer or the same -> skip
			if not silent: cprint(file.filename, "green")
			if not dryRun:
				sPath = pathJoin(sourceDir, file.filename)
				dPath = pathJoin(destDir  , file.filename)
				copy(sPath, dPath)
				utime(dPath, (file.st_atime, file.st_mtime))

	def delCopyFun(sourceFiles: list[LocalSFTPAttributes], sourcePlace: PLACE, destFiles: dict[str, LocalSFTPAttributes], destPlace: PLACE, sourceDir: str, destDir: str):
		if sourcePlace == PLACE.LOCAL and destPlace == PLACE.LOCAL:
			copy = bindKwarg(shutil.copyfile, follow_symlinks=False)
			utime = os.utime
			removeDest = os.remove
		elif sourcePlace == PLACE.REMOTE and destPlace == PLACE.LOCAL:
			copy = sftp.get
			utime = os.utime
			removeDest = os.remove
		elif sourcePlace == PLACE.LOCAL and destPlace == PLACE.REMOTE:
			copy = bindKwarg(sftp.put, confirm=False)
			utime = sftp.utime
			removeDest = sftp.remove
		elif sourcePlace == PLACE.REMOTE and destPlace == PLACE.REMOTE: #TODO correct this part as it does not do proper DEL_COPY
			copy = RemoteCopyBatch(sourceDir, destDir, "cp -u", True)
			copy.files = map(getAttr("filename"), sourceFiles)
			copy.finalize()
			return

		for file in sourceFiles:
			destFile = destFiles.pop(file.filename, None)
			if destFile and destFile.st_mtime >= file.st_mtime: continue # destination exists and is newer or the same -> skip
			if not silent: cprint(file.filename, "green")
			if not dryRun:
				sPath = pathJoin(sourceDir, file.filename)
				dPath = pathJoin(destDir  , file.filename)
				copy(sPath, dPath)
				utime(dPath, (file.st_atime, file.st_mtime))

		for file in destFiles.values():
			if not silent: cprint(file.filename, "red")
			if not dryRun:
				dPath = pathJoin(destDir, file.filename)
				removeDest(dPath)

	def moveFun(sourceFiles: list[LocalSFTPAttributes], sourcePlace: PLACE, destPlace: PLACE, sourceDir: str, destDir: str):
		if sourcePlace == PLACE.LOCAL and destPlace == PLACE.LOCAL:
			move = shutil.move
			def utime(x, y): pass
			def delete(x): pass
		elif sourcePlace == PLACE.REMOTE and destPlace == PLACE.LOCAL:
			move = sftp.get
			utime = os.utime
			delete = sftp.remove
		elif sourcePlace == PLACE.LOCAL and destPlace == PLACE.REMOTE:
			move = bindKwarg(sftp.put, confirm=False)
			utime = sftp.utime
			delete = os.remove
		elif sourcePlace == PLACE.REMOTE and destPlace == PLACE.REMOTE:
			copy = RemoteCopyBatch(sourceDir, destDir, "mv", True)
			copy.files = map(getAttr("filename"), sourceFiles)
			copy.finalize()
			return

		for file in sourceFiles:
			if not silent: cprint(file.filename, "green")
			if not dryRun:
				sPath = pathJoin(sourceDir, file.filename)
				dPath = pathJoin(destDir  , file.filename)
				move(sPath, dPath)
				utime(dPath, (file.st_atime, file.st_mtime))
				delete(sPath)

	# it's only noticeably faster if one of the remote folders that will be scanned has more than 5000 entries
	rld = RemoteListDir(ssh, init=False) # don't init the remote python script because remote_listdir_attr might not get called at all
	remote_listdir_attr = rld.listdir_attr

	localDirListCache = {}
	remoteDirListCache = {}
	for sourceDir, sourcePlace, destDir, destPlace, mode, filePatterns, defaultMatch in parsedOperations:
		if sourcePlace == PLACE.LOCAL:
			sourceDir = normalizeLocalFolderPath(sourceDir)
			assertLocalFolderExists(sourceDir)
			sourceDirListCache = localDirListCache
		elif sourcePlace == PLACE.REMOTE:
			sourceDir = normalizeRemoteFolderPath(sourceDir)
			assertRemoteFolderExists(sftp, sourceDir)
			sourceDirListCache = remoteDirListCache
		else:
			raise SimpleError(f"Invalid sourcePlace: {sourcePlace}")

		if destPlace == PLACE.LOCAL:
			destDir = normalizeLocalFolderPath(destDir)
			assertLocalFolderExists(destDir)
			destDirListCache = localDirListCache
		elif destPlace == PLACE.REMOTE:
			destDir = normalizeRemoteFolderPath(destDir)
			assertRemoteFolderExists(sftp, destDir)
			destDirListCache = remoteDirListCache
		else:
			raise SimpleError(f"Invalid destPlace: {destPlace}")

		if not silent:
			print()
			print(f"# {magentaSource} ({clr(sourcePlace._padded_name_, blueColor)}): {sourceDir}")
			print(f"# {cyanDest   }   ({clr(destPlace  ._padded_name_, blueColor)}): {destDir  }")
			print(f"# Mode: {clr(mode._padded_name_, blueColor)}")
			print(f"# File patterns: {" ".join(clr(pattern, "green" if matchVal else "red") for pattern, matchVal in filePatterns)} | {clr("defaultMatch", "green" if defaultMatch else "red")}")

		sourceFiles: list[LocalSFTPAttributes] = sourceDirListCache.get(sourceDir)
		if sourceFiles is None:
			sourceFiles = local_listdir_attr(sourceDir) if sourcePlace == PLACE.LOCAL else remote_listdir_attr(sourceDir)
			if mode == MODE.SYNC:
				sourceFiles = {file.filename: file for file in sourceFiles if filterFun(file, filePatterns, defaultMatch)}
			else:
				sourceFiles = tuple(file for file in sourceFiles if filterFun(file, filePatterns, defaultMatch))
			if cacheDirectoryListings: sourceDirListCache[sourceDir] = sourceFiles

		if not silent: print(f"# {magentaSource} file count: {len(sourceFiles)}")

		if not sourceFiles and mode != MODE.SYNC:
			continue

		if mode == MODE.SYNC and isinstance(sourceFiles, tuple):
			sourceFiles = {file.filename: file for file in sourceFiles}
		elif mode != MODE.SYNC and isinstance(sourceFiles, dict):
			sourceFiles = sourceFiles.values()

		if mode != MODE.MOVE:
			destFiles = destDirListCache.get(destDir)
			if destFiles is None:
				destFiles: list[LocalSFTPAttributes] = local_listdir_attr(destDir) if destPlace == PLACE.LOCAL else remote_listdir_attr(destDir)
				destFiles = {file.filename: file for file in destFiles if filterFun(file, filePatterns, defaultMatch)}
				if cacheDirectoryListings: destDirListCache[destDir] = destFiles

			if not silent: print(f"# {cyanDest}   file count: {len(destFiles)}")

			if not sourceFiles and not destFiles and mode == MODE.SYNC:
				continue

		match mode:
			case MODE.SYNC    : syncFun   (sourceFiles, sourcePlace, destFiles, destPlace, sourceDir, destDir)
			case MODE.COPY    : copyFun   (sourceFiles, sourcePlace, destFiles, destPlace, sourceDir, destDir)
			case MODE.DEL_COPY: delCopyFun(sourceFiles, sourcePlace, destFiles, destPlace, sourceDir, destDir)
			case MODE.MOVE    : moveFun   (sourceFiles, sourcePlace,            destPlace, sourceDir, destDir)
			case _: raise SimpleError(f"Invalid mode: {mode}")

	sftp.close()
	ssh.close()

	if not silent: print(f"\nExecution time: {perf_counter() - start:.3f} s")

if __name__ == "__main__":
	main()
