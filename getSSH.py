from termcolor import colored as clr, cprint
import socket
import paramiko
from paramiko.ssh_exception import (
	BadHostKeyException,
	AuthenticationException,
	SSHException,
	NoValidConnectionsError,
	PartialAuthentication,
)
from SimpleError import SimpleError

def getSSH(username: str, hostname: str, password: str, TIMEOUT: float, port = 22):
	ssh = paramiko.SSHClient()
	ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

	errorMessage = None
	try:
		print(f"Attempting to connect to {clr(username, "green")}@{clr(hostname, "green")} ...")
		ssh.connect(hostname, username=username, password=password, timeout=TIMEOUT, port=port)
	except BadHostKeyException:
		errorMessage = f"ERROR: The server's host key could not be verified for {hostname}"
	except AuthenticationException:
		errorMessage = f"ERROR: Authentication failed when connecting to {hostname}"
	except PartialAuthentication:
		errorMessage = f"ERROR: Partial authentication occurred when connecting to {hostname}"
	except socket.error as e:
		errorMessage = f"ERROR: Socket error while connecting to {hostname}: {e}"
	except NoValidConnectionsError:
		errorMessage = f"ERROR: No valid connections could be made to {hostname} (connection refused or unreachable)"
	except SSHException:
		errorMessage = f"ERROR: General SSH error occurred while connecting to {hostname} (probably timeout after {TIMEOUT} seconds)"

	if errorMessage:
		raise SimpleError(errorMessage)

	return ssh
