import sys as _sys

if _sys.platform == "win32": # Only load on Windows
	import ctypes as _ctypes
	from ctypes import wintypes as _wintypes

	# --- Constants ---
	_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
	_INVALID_HANDLE_VALUE = _wintypes.HANDLE(-1).value

	# NTSTATUS codes (subset)
	_STATUS_SUCCESS = 0x00000000
	_STATUS_NOT_IMPLEMENTED = 0xC0000002
	_STATUS_INVALID_INFO_CLASS = 0xC0000003
	_STATUS_INVALID_PARAMETER = 0xC000000D
	_STATUS_NOT_SUPPORTED = 0xC00000BB
	_STATUS_DIRECTORY_NOT_EMPTY = 0xC0000101

	# FILE_INFORMATION_CLASS
	_FileCaseSensitiveInformation = 71

	# Flags
	_CASE_SENSITIVE_DIR = 0x00000001

	# --- Structs ---
	class _IO_STATUS_BLOCK(_ctypes.Structure):
		_fields_ = [
			("Status", _wintypes.ULONG),
			("Information", _wintypes.ULONG),
		]

	class _FILE_CASE_SENSITIVE_INFORMATION(_ctypes.Structure):
		_fields_ = [
			("Flags", _wintypes.ULONG),
		]

	# --- DLLs ---
	_kernel32 = _ctypes.WinDLL("kernel32", use_last_error=True)
	_ntdll = _ctypes.WinDLL("ntdll", use_last_error=True)

	# --- Function prototypes ---
	_CreateFileW = _kernel32.CreateFileW
	_CreateFileW.argtypes = [
		_wintypes.LPCWSTR, _wintypes.DWORD, _wintypes.DWORD,
		_wintypes.LPVOID, _wintypes.DWORD, _wintypes.DWORD, _wintypes.HANDLE
	]
	_CreateFileW.restype = _wintypes.HANDLE

	_CloseHandle = _kernel32.CloseHandle
	_CloseHandle.argtypes = [_wintypes.HANDLE]
	_CloseHandle.restype = _wintypes.BOOL

	_NtQueryInformationFile = _ntdll.NtQueryInformationFile
	_NtQueryInformationFile.argtypes = [
		_wintypes.HANDLE,
		_ctypes.POINTER(_IO_STATUS_BLOCK),
		_ctypes.POINTER(_FILE_CASE_SENSITIVE_INFORMATION),
		_wintypes.ULONG,
		_wintypes.INT
	]
	_NtQueryInformationFile.restype = _wintypes.ULONG

	def isFolderCaseSensitive(path: str, throw_on_error: bool = True) -> bool:
		handle = _CreateFileW(
			str(path),
			0,  # no read access needed
			3,  # FILE_SHARE_READ | FILE_SHARE_WRITE
			None,
			3,  # OPEN_EXISTING
			_FILE_FLAG_BACKUP_SEMANTICS,
			None
		)

		if handle == _INVALID_HANDLE_VALUE:
			raise _ctypes.WinError(_ctypes.get_last_error())

		try:
			iosb = _IO_STATUS_BLOCK()
			case_info = _FILE_CASE_SENSITIVE_INFORMATION()

			status = _NtQueryInformationFile(
				handle,
				_ctypes.byref(iosb),
				_ctypes.byref(case_info),
				_ctypes.sizeof(case_info),
				_FileCaseSensitiveInformation
			)

			if status == _STATUS_SUCCESS:
				return bool(case_info.Flags & _CASE_SENSITIVE_DIR)
			elif status in (
				_STATUS_NOT_IMPLEMENTED,
				_STATUS_INVALID_INFO_CLASS,
				_STATUS_INVALID_PARAMETER,
				_STATUS_NOT_SUPPORTED,
			):
				if throw_on_error:
					raise RuntimeError("Case sensitivity not supported on this Windows version.")
				return False
			else:
				raise RuntimeError(f"Unexpected NTSTATUS: 0x{status:08X}")
		finally:
			_CloseHandle(handle)
else:
	def isFolderCaseSensitive(destFolderParam: str) -> bool:
		raise NotImplementedError("Case sensitivity check only works on Windows")

if __name__ == "__main__": # Example usage
	from pathlib import Path as _Path

	from myLibs.isFolderCaseSensitive import isFolderCaseSensitive
	print(isFolderCaseSensitive(_Path(__file__).resolve().parent))
