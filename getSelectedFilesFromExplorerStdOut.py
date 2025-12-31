from pathlib import Path; __package__ = Path(__file__).resolve().parent.name # To be able to use relative imports

from .getSelectedFilesFromExplorer import getSelectedFilesFromExplorer

selectedFiles = getSelectedFilesFromExplorer(infoAndError=False)

print("\n".join(selectedFiles), end="")
