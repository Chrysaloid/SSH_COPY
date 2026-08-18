from pathlib import Path; __package__ = __package__ or Path(__file__).resolve().parent.name # To be able to use relative imports when run directly - never override a __package__ Python already set (see README)

from .getSelectedFilesFromExplorer import getSelectedFilesFromExplorer

selectedFiles = getSelectedFilesFromExplorer(infoAndError=False)

print("\n".join(selectedFiles), end="")
