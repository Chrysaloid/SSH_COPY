import sys

from termcolor import colored as clr

from .commonConstants import COLOR_OK
from .SimpleError import SimpleError

def getSelectedFilesFromStdIn(fileIO = sys.stdin):
	selectedFiles = [line.strip() for line in fileIO if line.strip()]

	if not selectedFiles:
		raise SimpleError("No files/folders selected")
	else:
		print(f"{clr(len(selectedFiles), COLOR_OK)} file(s)/folder(s) selected")

	return selectedFiles
