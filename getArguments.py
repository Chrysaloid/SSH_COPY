import sys
from termcolor import colored as clr
from SimpleError import SimpleError

def getArguments(expectedNumArgs: int):
	if len(sys.argv) < expectedNumArgs:
		raise SimpleError(f"{clr("Not enough input arguments:", "red")} {clr(len(sys.argv), "yellow")} were provided out of required {expectedNumArgs}", "")

	return sys.argv[1:expectedNumArgs]
