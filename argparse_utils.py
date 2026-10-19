from pathlib import Path as _Path; __package__ = __package__ or _Path(__file__).resolve().parent.name # To be able to use relative imports when run directly - never override a __package__ Python already set (see README)

import argparse as _argparse
from fnmatch import fnmatchcase as _fnmatchcase
import sys as _sys
from typing import Callable as _Callable

from termcolor import colored as _clr

from .common_constants import COLOR_ERROR as _COLOR_ERROR

COMMON_FORMATTER_CLASS = lambda prog: _argparse.HelpFormatter(prog, max_help_position=30, width=100)

class ArgumentParser_colored_error(_argparse.ArgumentParser):
	def __init__(self, *args, error_color=_COLOR_ERROR, **kwargs):
		super().__init__(*args, **kwargs)
		self.error_color = error_color

	def error(self, message):
		self.print_usage(_sys.stderr) # print usage as usual
		self.exit(2, _clr(f"{self.prog}: error: {message}\n", self.error_color))

class No_repeat_Action(_argparse.Action):
	def __call__(self, parser, namespace, values, option_string=None):
		if getattr(namespace, self.dest, None) is not None:
			raise _argparse.ArgumentError(self, f"may only be specified once")
		setattr(namespace, self.dest, values)

class Name_filter:
	def __init__(self, pattern: str, match_val: bool, matching_func: _Callable[[str, str], bool]):
		self.pattern = pattern
		self.match_val = match_val
		self.matching_func = matching_func

def filename_match_case(name: str, path: str, pat: str) -> bool:
	return _fnmatchcase(name, pat)

def filename_match_not_case(name: str, path: str, pat: str) -> bool:
	# In general case one would use the following:
	# return fnmatchcase(name.lower(), pat.lower())

	# In our case we skip the .lower() for pat as we will do that only once in the __call__ method
	return _fnmatchcase(name.lower(), pat)

def path_match_case(name: str, path: str, pat: str) -> bool:
	""" I.e. pat = `/some/folder` should match paths `/some` and `/some/folder/file` so it allows
	recursion to get to `/some/folder` from `/` and allows recursion to go to subfolders and files of
	`/some/folder` """
	return path.startswith(pat) or pat.startswith(path)

def path_match_not_case(name: str, path: str, pat: str) -> bool:
	path_lower = path.lower()
	return path_lower.startswith(pat) or pat.startswith(path_lower)

class Include_exclude_Action(_argparse.Action):
	dest_defaults = {}

	def __init__(self, option_strings: list[str], dest, **kwargs):
		super().__init__(option_strings, dest, **kwargs)

		if len(option_strings) != 2:
			raise ValueError(f"Include_exclude_Action should always have short and long parameter names specified")

		long_name = max(option_strings, key=len)

		self.match_val = long_name.startswith("--include")
		self.is_path = long_name.endswith("path")
		self.is_case = "case" in long_name
		self.entry_type = "file" if "file" in long_name else "folder"

		if self.is_path:
			if self.is_case:
				self.matching_func = path_match_case
			else:
				self.matching_func = path_match_not_case
		else:
			if self.is_case:
				self.matching_func = filename_match_case
			else:
				self.matching_func = filename_match_not_case

	def __call__(self, parser, namespace, values, option_string=None):
		# Ensure the target list exists
		items = getattr(namespace, self.dest, None)
		if items is None:
			items = []
			setattr(namespace, self.dest, items)

		# If --include-* argument was first - by default exclude
		# If --exclude-* argument was first - by default include
		if self.entry_type not in Include_exclude_Action.dest_defaults:
			Include_exclude_Action.dest_defaults[self.entry_type] = not self.match_val

		for pattern in values:
			pattern = pattern.strip()
			if pattern:
				pattern = pattern if self.is_case else pattern.lower()
				pattern = pattern.replace("\\", "/").rstrip("/") # not conditional to support .gitignore style folder mathing
				items.append(Name_filter(
					pattern,
					self.match_val,
					self.matching_func
				))
