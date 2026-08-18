import sys as _sys

WINDOWS = _sys.platform == "win32"
LINUX = not WINDOWS

if __name__ == "__main__": # Example usage
	from myLibs.mySystem import LINUX, WINDOWS

	print(f"WINDOWS: {WINDOWS}")
	print(f"LINUX: {LINUX}")
