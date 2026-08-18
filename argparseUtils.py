from pathlib import Path as _Path; __package__ = __package__ or _Path(__file__).resolve().parent.name # To be able to use relative imports when run directly - never override a __package__ Python already set (see README)

import argparse as _argparse
from fnmatch import fnmatchcase as _fnmatchcase
import sys as _sys
from typing import Callable as _Callable

from termcolor import colored as _clr

from .commonConstants import COLOR_ERROR as _COLOR_ERROR

COMMON_FORMATTER_CLASS = lambda prog: _argparse.HelpFormatter(prog, max_help_position=30, width=100)

class ArgumentParser_ColoredError(_argparse.ArgumentParser):
	def __init__(self, *args, errorColor=_COLOR_ERROR, **kwargs):
		super().__init__(*args, **kwargs)
		self.errorColor = errorColor

	def error(self, message):
		self.print_usage(_sys.stderr) # print usage as usual
		self.exit(2, _clr(f"{self.prog}: error: {message}\n", self.errorColor))

class NoRepeatAction(_argparse.Action):
	def __call__(self, parser, namespace, values, option_string=None):
		if getattr(namespace, self.dest, None) is not None:
			raise _argparse.ArgumentError(self, f"may only be specified once")
		setattr(namespace, self.dest, values)

class NameFilter:
	def __init__(self, pattern: str, matchVal: bool, matchingFunc: _Callable[[str, str], bool]):
		self.pattern = pattern
		self.matchVal = matchVal
		self.matchingFunc = matchingFunc

def filenameMatchCase(name: str, path: str, pat: str) -> bool:
	return _fnmatchcase(name, pat)

def filenameMatchNotCase(name: str, path: str, pat: str) -> bool:
	# In general case one would use the following:
	# return fnmatchcase(name.lower(), pat.lower())

	# In our case we skip the .lower() for pat as we will do that only once in the __call__ method
	return _fnmatchcase(name.lower(), pat)

def pathMatchCase(name: str, path: str, pat: str) -> bool:
	""" I.e. pat = `/some/folder` should match paths `/some` and `/some/folder/file` so it allows
	recursion to get to `/some/folder` from `/` and allows recursion to go to subfolders and files of
	`/some/folder` """
	return path.startswith(pat) or pat.startswith(path)

def pathMatchNotCase(name: str, path: str, pat: str) -> bool:
	pathLower = path.lower()
	return pathLower.startswith(pat) or pat.startswith(pathLower)

class IncludeExcludeAction(_argparse.Action):
	destDefaults = {}

	def __init__(self, option_strings: list[str], dest, **kwargs):
		super().__init__(option_strings, dest, **kwargs)

		if len(option_strings) != 2:
			raise ValueError(f"IncludeExcludeAction should always have short and long parameter names specified")

		longName = max(option_strings, key=len)

		self.matchVal = longName.startswith("--include")
		self.isPath = longName.endswith("path")
		self.isCase = "case" in longName
		self.entryType = "file" if "file" in longName else "folder"

		if self.isPath:
			if self.isCase:
				self.matchingFunc = pathMatchCase
			else:
				self.matchingFunc = pathMatchNotCase
		else:
			if self.isCase:
				self.matchingFunc = filenameMatchCase
			else:
				self.matchingFunc = filenameMatchNotCase

	def __call__(self, parser, namespace, values, option_string=None):
		# Ensure the target list exists
		items = getattr(namespace, self.dest, None)
		if items is None:
			items = []
			setattr(namespace, self.dest, items)

		# If --include-* argument was first - by default exclude
		# If --exclude-* argument was first - by default include
		if self.entryType not in IncludeExcludeAction.destDefaults:
			IncludeExcludeAction.destDefaults[self.entryType] = not self.matchVal

		for pattern in values:
			pattern = pattern.strip()
			if pattern:
				pattern = pattern if self.isCase else pattern.lower()
				pattern = pattern.replace("\\", "/").rstrip("/") # not conditional to support .gitignore style folder mathing
				items.append(NameFilter(
					pattern,
					self.matchVal,
					self.matchingFunc
				))
