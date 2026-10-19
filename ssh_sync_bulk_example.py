import sys; from pathlib import Path; p = Path(__file__).resolve().parent; __package__ = p.name; sys.path.append(p.parent.as_posix()) # To be able to use relative imports

from argparse import Namespace

from .ssh_sync_bulk import main, Mode, Place

main(Namespace(
	username                 = "Test",
	hostname                 = "192.168.0.121",
	hosts                    = "", # Test@192.168.0.121:22
	password                 = None,
	port                     = 22,
	timeout                  = 5,
	verbose                  = False,
	silent                   = False,
	dry_run                  = False,
	remote_os                = "windows",
	cache_directory_listings = True,
	operations               = (
		# source_dir                  , source_place, dest_dir                          , dest_place , mode     , file_patterns    , default_match
		(f"G:/Test/Nowy folder/Source", Place.REMOTE, f"G:/Test/Nowy folder/Destination", Place.LOCAL, Mode.SYNC, [("*.txt", True)], True         ),
	),
))
