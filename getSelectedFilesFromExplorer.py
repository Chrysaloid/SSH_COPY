from termcolor import colored as clr, cprint
import win32com.client
import win32gui
from SimpleError import SimpleError

def getTopmostExplorerHwnd() -> int | None:
	"""Get the HWND of the topmost (most recently active) Explorer window."""
	topmostHwnd = None

	def enumHandler(hwnd: int, _):
		nonlocal topmostHwnd
		if win32gui.IsWindowVisible(hwnd) and win32gui.GetClassName(hwnd) == "CabinetWClass": # class of Explorer windows
			topmostHwnd = hwnd
			return False # Stop at first (topmost) Explorer window
		return True
	win32gui.EnumWindows(enumHandler, None)

	return topmostHwnd

def getSelectedFilesFromExplorer(infoAndError=True, forwardSlashes=True) -> list[str]:
	targetHwnd = getTopmostExplorerHwnd()

	selectedFiles = []
	if targetHwnd is not None:
		shell = win32com.client.Dispatch("Shell.Application")

		for window in shell.Windows():
			try:
				if window.HWND == targetHwnd:
					if forwardSlashes:
						selectedFiles = [item.Path.replace("\\", "/") for item in window.Document.SelectedItems()]
					else:
						selectedFiles = [item.Path for item in window.Document.SelectedItems()]
			except Exception as e:
				print(e)

	if infoAndError:
		if not selectedFiles:
			raise SimpleError("No files/folders selected")
		else:
			print(f"{clr(len(selectedFiles), "green")} file(s)/folder(s) selected")

	return selectedFiles
