import os

class LocalSFTPAttributes:
	"""Mimics paramiko.sftp_attr.SFTPAttributes for local files."""
	def __init__(self, entry: os.DirEntry):
		info = entry.stat(follow_symlinks=False)
		self.filename = entry.name
		self.st_mode = info.st_mode
		self.st_size = info.st_size
		self.st_uid = info.st_uid
		self.st_gid = info.st_gid
		self.st_atime = int(info.st_atime)
		self.st_mtime = int(info.st_mtime)

	def __repr__(self):
		return f"<LocalSFTPAttributes filename={self.filename!r} size={self.st_size}>"

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
