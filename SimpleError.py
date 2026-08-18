from pathlib import Path as _Path; __package__ = _Path(__file__).resolve().parent.name # To be able to use relative imports

import sys as _sys

from termcolor import colored as _clr

from .commonConstants import COLOR_ERROR as _COLOR_ERROR

class SimpleError(Exception):
	def __init__(self, message: str, color = _COLOR_ERROR):
		""" Print (in red) only the message without the traceback """
		if color:
			self.message = _clr(message, color)
		else:
			self.message = message

	def __str__(self):
		return self.message

def _customExcepthook(exc_type, exc_value, exc_traceback):
	if issubclass(exc_type, SimpleError):
		if exc_value.message: print(exc_value.message)
	else: # fallback to normal behavior
		_sys.__excepthook__(exc_type, exc_value, exc_traceback)

_sys.excepthook = _customExcepthook

if __name__ == "__main__": # Example usage
	from myLibs.SimpleError import SimpleError

	# raise SimpleError("","")
	raise SimpleError("Something went wrong")
