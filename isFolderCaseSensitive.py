import sys

if sys.platform == "win32": # Only load on Windows
	import ctypes
	from ctypes import wintypes

	# --- Constants ---
	FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
	INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

	# NTSTATUS codes (subset)
	STATUS_SUCCESS = 0x00000000
	STATUS_NOT_IMPLEMENTED = 0xC0000002
	STATUS_INVALID_INFO_CLASS = 0xC0000003
	STATUS_INVALID_PARAMETER = 0xC000000D
	STATUS_NOT_SUPPORTED = 0xC00000BB
	STATUS_DIRECTORY_NOT_EMPTY = 0xC0000101

	# FILE_INFORMATION_CLASS
	FileCaseSensitiveInformation = 71

	# Flags
	CASE_SENSITIVE_DIR = 0x00000001

	# --- Structs ---
	class IO_STATUS_BLOCK(ctypes.Structure):
		_fields_ = [
			("Status", wintypes.ULONG),
			("Information", wintypes.ULONG),
		]

	class FILE_CASE_SENSITIVE_INFORMATION(ctypes.Structure):
		_fields_ = [
			("Flags", wintypes.ULONG),
		]

	# --- DLLs ---
	kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
	ntdll = ctypes.WinDLL("ntdll", use_last_error=True)

	# --- Function prototypes ---
	CreateFileW = kernel32.CreateFileW
	CreateFileW.argtypes = [
		wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
		wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE
	]
	CreateFileW.restype = wintypes.HANDLE

	CloseHandle = kernel32.CloseHandle
	CloseHandle.argtypes = [wintypes.HANDLE]
	CloseHandle.restype = wintypes.BOOL

	NtQueryInformationFile = ntdll.NtQueryInformationFile
	NtQueryInformationFile.argtypes = [
		wintypes.HANDLE,
		ctypes.POINTER(IO_STATUS_BLOCK),
		ctypes.POINTER(FILE_CASE_SENSITIVE_INFORMATION),
		wintypes.ULONG,
		wintypes.INT
	]
	NtQueryInformationFile.restype = wintypes.ULONG

	def isFolderCaseSensitive(path: str, throw_on_error: bool = True) -> bool:
		handle = CreateFileW(
			path,
			0,  # no read access needed
			3,  # FILE_SHARE_READ | FILE_SHARE_WRITE
			None,
			3,  # OPEN_EXISTING
			FILE_FLAG_BACKUP_SEMANTICS,
			None
		)

		if handle == INVALID_HANDLE_VALUE:
			raise ctypes.WinError(ctypes.get_last_error())

		try:
			iosb = IO_STATUS_BLOCK()
			case_info = FILE_CASE_SENSITIVE_INFORMATION()

			status = NtQueryInformationFile(
				handle,
				ctypes.byref(iosb),
				ctypes.byref(case_info),
				ctypes.sizeof(case_info),
				FileCaseSensitiveInformation
			)

			if status == STATUS_SUCCESS:
				return bool(case_info.Flags & CASE_SENSITIVE_DIR)
			elif status in (
				STATUS_NOT_IMPLEMENTED,
				STATUS_INVALID_INFO_CLASS,
				STATUS_INVALID_PARAMETER,
				STATUS_NOT_SUPPORTED,
			):
				if throw_on_error:
					raise RuntimeError("Case sensitivity not supported on this Windows version.")
				return False
			else:
				raise RuntimeError(f"Unexpected NTSTATUS: 0x{status:08X}")
		finally:
			CloseHandle(handle)
else:
	def isFolderCaseSensitive(destFolderParam: str) -> bool:
		raise NotImplementedError("Case sensitivity check only works on Windows")
