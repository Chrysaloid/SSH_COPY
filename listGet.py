def listGet(lst: list, idx: int, default = None):
	""" like dict.get("key", "default") """
	return lst[idx] if 0 <= idx < len(lst) else default

if __name__ == "__main__": # Example usage
	from myLibs.listGet import listGet

	print(listGet("abc", 2))
	print(listGet("abc", 3))

# python listGet.py
