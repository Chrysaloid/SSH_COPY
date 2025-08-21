from termcolor import colored as clr, cprint
import win32com.client
import win32gui
from SimpleError import SimpleError

def getTopmostExplorerHwnd():
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

def getSelectedFilesFromExplorerRaw():
	targetHwnd = getTopmostExplorerHwnd()
	if not targetHwnd:
		return []

	shell = win32com.client.Dispatch("Shell.Application")

	for window in shell.Windows():
		try:
			if window.HWND == targetHwnd:
				return [item.Path for item in window.Document.SelectedItems()]
		except Exception as e:
			print(e)

	return []

def getSelectedFilesFromExplorer():
	selectedFiles = getSelectedFilesFromExplorerRaw()

	if not selectedFiles:
		raise SimpleError("No files/folders selected")
	else:
		print(f"{clr(len(selectedFiles), "green")} file(s)/folder(s) selected")

	return selectedFiles
