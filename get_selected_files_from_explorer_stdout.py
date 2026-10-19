from pathlib import Path; __package__ = __package__ or Path(__file__).resolve().parent.name # To be able to use relative imports when run directly - never override a __package__ Python already set (see README)

from .get_selected_files_from_explorer import get_selected_files_from_explorer

selected_files = get_selected_files_from_explorer(info_and_error=False)

print("\n".join(selected_files), end="")
