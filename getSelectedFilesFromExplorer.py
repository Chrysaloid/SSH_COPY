from pathlib import Path as _Path; __package__ = __package__ or _Path(__file__).resolve().parent.name # To be able to use relative imports when run directly - never override a __package__ Python already set (see README)

import ctypes as _ctypes

from termcolor import colored as _clr
from win32com import client as _win32com_client
import win32gui as _win32gui

from .commonConstants import COLOR_OK as _COLOR_OK
from .SimpleError import SimpleError as _SimpleError

def _getTopmostExplorerHwnd() -> int | None:
	"""Get the HWND of the topmost (most recently active) Explorer window."""
	topmostHwnd = None

	def enumHandler(hwnd: int, _):
		nonlocal topmostHwnd
		if _win32gui.IsWindowVisible(hwnd) and _win32gui.GetClassName(hwnd) == "CabinetWClass": # class of Explorer windows
			topmostHwnd = hwnd
			return False # Stop at first (topmost) Explorer window
		return True

	_ctypes.windll.kernel32.SetLastError(0) # some modules (i.e. argparse) set LastError and win32gui.EnumWindows doesn't like it

	_win32gui.EnumWindows(enumHandler, None)

	return topmostHwnd

def getSelectedFilesFromExplorer(infoAndError=True, forwardSlashes=True) -> list[str]:
	targetHwnd = _getTopmostExplorerHwnd()

	selectedFiles = []
	if targetHwnd is not None:
		shell = _win32com_client.Dispatch("Shell.Application")

		for window in shell.Windows():
			try:
				if window.HWND == targetHwnd:
					if forwardSlashes:
						selectedFiles = [item.Path.replace("\\", "/") for item in window.Document.SelectedItems()]
					else:
						selectedFiles = [item.Path for item in window.Document.SelectedItems()]
					break
			except Exception as e:
				print(e)

	if infoAndError:
		if not selectedFiles:
			raise _SimpleError("No files/folders selected")
		else:
			print(f"{_clr(len(selectedFiles), _COLOR_OK)} file(s)/folder(s) selected")

	return selectedFiles

if __name__ == "__main__": # Example usage
	from myLibs.getSelectedFilesFromExplorer import getSelectedFilesFromExplorer

	print(getSelectedFilesFromExplorer(False))
