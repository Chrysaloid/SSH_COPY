from pathlib import Path as _Path; __package__ = __package__ or _Path(__file__).resolve().parent.name # To be able to use relative imports when run directly - never override a __package__ Python already set (see README)

import sys as _sys

from termcolor import colored as _clr

from .commonConstants import COLOR_OK as _COLOR_OK
from .SimpleError import SimpleError as _SimpleError

def getSelectedFilesFromStdIn(fileIO = _sys.stdin):
	selectedFiles = [line.strip() for line in fileIO if line.strip()]

	if not selectedFiles:
		raise _SimpleError("No files/folders selected")
	else:
		print(f"{_clr(len(selectedFiles), _COLOR_OK)} file(s)/folder(s) selected")

	return selectedFiles
