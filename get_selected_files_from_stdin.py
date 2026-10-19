from pathlib import Path as _Path; __package__ = __package__ or _Path(__file__).resolve().parent.name # To be able to use relative imports when run directly - never override a __package__ Python already set (see README)

import sys as _sys

from termcolor import colored as _clr

from .common_constants import COLOR_OK as _COLOR_OK
from .simple_error import Simple_error as _Simple_error

def get_selected_files_from_stdin(file_io = _sys.stdin):
	selected_files = [line.strip() for line in file_io if line.strip()]

	if not selected_files:
		raise _Simple_error("No files/folders selected")
	else:
		print(f"{_clr(len(selected_files), _COLOR_OK)} file(s)/folder(s) selected")

	return selected_files
