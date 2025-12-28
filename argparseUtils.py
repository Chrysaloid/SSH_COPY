import argparse
import sys
from fnmatch import fnmatchcase
from typing import Callable

from termcolor import colored as clr

from .commonConstants import COLOR_ERROR

COMMON_FORMATTER_CLASS = lambda prog: argparse.HelpFormatter(prog, max_help_position=30, width=100)

class ArgumentParser_ColoredError(argparse.ArgumentParser):
	def __init__(self, *args, errorColor=COLOR_ERROR, **kwargs):
		super().__init__(*args, **kwargs)
		self.errorColor = errorColor

	def error(self, message):
		self.print_usage(sys.stderr) # print usage as usual
		self.exit(2, clr(f"{self.prog}: error: {message}\n", self.errorColor))

class NoRepeatAction(argparse.Action):
	def __call__(self, parser, namespace, values, option_string=None):
		if getattr(namespace, self.dest, None) is not None:
			raise argparse.ArgumentError(self, f"may only be specified once")
		setattr(namespace, self.dest, values)

class NameFilter:
	def __init__(self, pattern: str, matchVal: bool, matchingFunc: Callable):
		self.pattern = pattern
		self.matchVal = matchVal
		self.matchingFunc = matchingFunc

def fnmatchNotCase(name: str, pat: str) -> bool:
	# In general case one would use the following:
	# return fnmatchcase(name.lower(), pat.lower())

	# In our case we skip the .lower() for pat as we will do that only once in the __call__ method
	return fnmatchcase(name.lower(), pat)

class IncludeExcludeAction(argparse.Action):
	destDefaults = {}

	def __init__(self, option_strings: list[str], dest, **kwargs):
		super().__init__(option_strings, dest, **kwargs)

		if len(option_strings) != 2:
			raise ValueError(f"IncludeExcludeAction should always have short and long parameter names specified")

		longName = max(option_strings, key=len)

		self.matchVal = longName.startswith("--include")
		self.matchingFunc = fnmatchcase if longName.endswith("case") else fnmatchNotCase

	def __call__(self, parser, namespace, values, option_string=None):
		# Ensure the target list exists
		items = getattr(namespace, self.dest, None)
		if items is None:
			items = []
			setattr(namespace, self.dest, items)

		# If --include-* argument was first - by default exclude
		# If --exclude-* argument was first - by default include
		if self.dest not in IncludeExcludeAction.destDefaults:
			IncludeExcludeAction.destDefaults[self.dest] = not self.matchVal

		for pattern in values:
			items.append(NameFilter(
				pattern if self.matchingFunc is fnmatchcase else pattern.lower(),
				self.matchVal,
				self.matchingFunc
			))
