from pythonping import ping

def isOnline(ip: str, timeout = 0.5) -> bool:
	try:
		return ping(ip, timeout=timeout, count=1, size=32).success()
	except Exception:
		return False
