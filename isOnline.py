from pythonping import ping
from SimpleError import SimpleError

def isOnline(ip: str, timeout = 0.5) -> bool:
	try:
		return ping(ip, timeout=timeout, count=1, size=32).success()
	except Exception:
		return False

def exitIfOffline(ip: str, *args, **kwargs):
	if not isOnline(ip, *args, **kwargs):
		raise SimpleError(f"The host {ip} is offline")
