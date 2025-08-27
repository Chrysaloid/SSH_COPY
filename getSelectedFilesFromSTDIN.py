from termcolor import colored as clr
import sys
from SimpleError import SimpleError

def getSelectedFilesFromStdIn(fileIO = sys.stdin):
	selectedFiles = [line.strip() for line in fileIO if line.strip()]

	if not selectedFiles:
		raise SimpleError("No files/folders selected")
	else:
		print(f"{clr(len(selectedFiles), "green")} file(s)/folder(s) selected")

	return selectedFiles
