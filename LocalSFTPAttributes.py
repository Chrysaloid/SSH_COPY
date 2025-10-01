import os

class LocalSFTPAttributes:
	"""Mimics paramiko.sftp_attr.SFTPAttributes for local files."""
	def __init__(self, entry: os.DirEntry):
		info = entry.stat(follow_symlinks=False)
		self.filename = entry.name
		self.st_mode  = info.st_mode
		self.st_size  = info.st_size
		self.st_uid   = info.st_uid
		self.st_gid   = info.st_gid
		self.st_atime = int(info.st_atime)
		self.st_mtime = int(info.st_mtime)

	def __repr__(self):
		return f"<LocalSFTPAttributes filename={self.filename!r} size={self.st_size}>"

	@classmethod
	def from_values(
		cls,
		filename: str,
		st_mode : int = 0,
		st_size : int = 0,
		st_uid  : int = 0,
		st_gid  : int = 0,
		st_atime: int = 0,
		st_mtime: int = 0
	):
		"""Constructs a LocalSFTPAttributes from explicit values."""
		obj = cls.__new__(cls) # bypass __init__
		obj.filename = filename
		obj.st_mode  = st_mode
		obj.st_size  = st_size
		obj.st_uid   = st_uid
		obj.st_gid   = st_gid
		obj.st_atime = st_atime
		obj.st_mtime = st_mtime
		return obj

def local_listdir_attr(path: str):
	"""
	Local equivalent of sftp.listdir_attr(path).
	Returns a list of LocalSFTPAttributes by default.
	"""
	entries = []
	with os.scandir(path) as it:
		for entry in it:
			entries.append(LocalSFTPAttributes(entry))
	return entries

def local_listdir_attr_gen(path: str):
	"""
	Generator equivalent of local_listdir_attr
	"""
	with os.scandir(path) as it:
		for entry in it:
			yield LocalSFTPAttributes(entry)
