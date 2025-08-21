from termcolor import colored as clr
import sys
from SimpleError import SimpleError

def getSelectedFilesFromStdIn():
	selectedFiles = sys.stdin.read().splitlines()

	if not selectedFiles:
		raise SimpleError("No files/folders selected")
	else:
		print(f"{clr(len(selectedFiles), "green")} file(s)/folder(s) selected")

	return selectedFiles
