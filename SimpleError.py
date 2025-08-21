import sys
from termcolor import colored as clr

class SimpleError(Exception):
	def __init__(self, message, color = "red"):
		if color:
			self.message = clr(message, color)
		else:
			self.message = message

	def __str__(self):
		return self.message

def custom_excepthook(exc_type, exc_value, exc_traceback):
	if issubclass(exc_type, SimpleError):
		print(exc_value)
	else: # fallback to normal behavior
		sys.__excepthook__(exc_type, exc_value, exc_traceback)

sys.excepthook = custom_excepthook

# Example:
# raise simpleError("Something went wrong")
