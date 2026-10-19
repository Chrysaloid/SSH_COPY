def list_get(lst: list, idx: int, default = None):
	""" like dict.get("key", "default") """
	return lst[idx] if 0 <= idx < len(lst) else default

if __name__ == "__main__": # Example usage
	from my_libs.list_get import list_get

	print(list_get("abc", 2))
	print(list_get("abc", 3))

# python list_get.py
