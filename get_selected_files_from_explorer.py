from pathlib import Path as _Path; __package__ = __package__ or _Path(__file__).resolve().parent.name # To be able to use relative imports when run directly - never override a __package__ Python already set (see README)

import ctypes as _ctypes

from termcolor import colored as _clr
from win32com import client as _win32com_client
import win32gui as _win32gui

from .common_constants import COLOR_OK as _COLOR_OK
from .simple_error import Simple_error as _Simple_error

def _get_topmost_explorer_hwnd() -> int | None:
	"""Get the HWND of the topmost (most recently active) Explorer window."""
	topmost_hwnd = None

	def enum_handler(hwnd: int, _):
		nonlocal topmost_hwnd
		if _win32gui.IsWindowVisible(hwnd) and _win32gui.GetClassName(hwnd) == "CabinetWClass": # class of Explorer windows
			topmost_hwnd = hwnd
			return False # Stop at first (topmost) Explorer window
		return True

	_ctypes.windll.kernel32.SetLastError(0) # some modules (i.e. argparse) set LastError and win32gui.EnumWindows doesn't like it

	_win32gui.EnumWindows(enum_handler, None)

	return topmost_hwnd

def get_selected_files_from_explorer(info_and_error=True, forward_slashes=True) -> list[str]:
	target_hwnd = _get_topmost_explorer_hwnd()

	selected_files = []
	if target_hwnd is not None:
		shell = _win32com_client.Dispatch("Shell.Application")

		for window in shell.Windows():
			try:
				if window.HWND == target_hwnd:
					if forward_slashes:
						selected_files = [item.Path.replace("\\", "/") for item in window.Document.SelectedItems()]
					else:
						selected_files = [item.Path for item in window.Document.SelectedItems()]
					break
			except Exception as e:
				print(e)

	if info_and_error:
		if not selected_files:
			raise _Simple_error("No files/folders selected")
		else:
			print(f"{_clr(len(selected_files), _COLOR_OK)} file(s)/folder(s) selected")

	return selected_files

if __name__ == "__main__": # Example usage
	from my_libs.get_selected_files_from_explorer import get_selected_files_from_explorer

	print(get_selected_files_from_explorer(False))
