from pathlib import Path as _Path; __package__ = __package__ or _Path(__file__).resolve().parent.name # To be able to use relative imports when run directly - never override a __package__ Python already set (see README)

import sys as _sys

from termcolor import colored as _clr

from .common_constants import COLOR_ERROR as _COLOR_ERROR

class Simple_error(Exception):
	def __init__(self, message: str, color = _COLOR_ERROR):
		""" Print (in red) only the message without the traceback """
		if color:
			self.message = _clr(message, color)
		else:
			self.message = message

	def __str__(self):
		return self.message

# Chain to whatever was installed before us instead of jumping straight back to the
# default. Costs nothing in the normal case, and it is what makes a SECOND copy of this
# module harmless: if this file ever gets imported twice under two names (see the note on
# line 1 - a symlink plus a clobbered __package__ used to do exactly that), the two
# Simple_error classes are different classes, so each hook rejects the other's exceptions.
# Chained, the newest hook simply hands those to the older one, which does recognise them.
# Replacing the chain with _sys.__excepthook__ printed a full traceback instead.
_previous_excepthook = _sys.excepthook

def _custom_excepthook(exc_type, exc_value, exc_traceback):
	if issubclass(exc_type, Simple_error):
		if exc_value.message: print(exc_value.message)
	else: # fallback to whatever handled exceptions before this module was imported
		_previous_excepthook(exc_type, exc_value, exc_traceback)

_sys.excepthook = _custom_excepthook

if __name__ == "__main__": # Example usage
	from my_libs.simple_error import Simple_error

	# raise Simple_error("","")
	raise Simple_error("Something went wrong")
