import sys
from termcolor import colored as clr
from SimpleError import SimpleError

def getArguments():
	if len(sys.argv) < 5:
		raise SimpleError(f"{clr("Not enough input arguments:", "red")} {clr(len(sys.argv), "yellow")} were provided out of required 5", "")

	return sys.argv[1:5] # username, hostname, password, remoteFolder
