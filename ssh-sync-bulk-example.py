import sys; from pathlib import Path; p = Path(__file__).resolve().parent; __package__ = p.name; sys.path.append(p.parent.as_posix()) # To be able to use relative imports

from argparse import Namespace

from .SSH_SYNC_BULK import main, MODE, PLACE

main(Namespace(
	username               = "Test",
	hostname               = "192.168.0.121",
	password               = None,
	port                   = 22,
	timeout                = 5,
	verbose                = False,
	silent                 = False,
	dryRun                 = False,
	remoteOs               = "windows",
	cacheDirectoryListings = True,
	operations             = (
		# sourceDir                   , sourcePlace , destDir                           , destPlace  , mode     , filePatterns     , defaultMatch
		(f"G:/Test/Nowy folder/Source", PLACE.REMOTE, f"G:/Test/Nowy folder/Destination", PLACE.LOCAL, MODE.SYNC, [("*.txt", True)], True        ),
	),
))
