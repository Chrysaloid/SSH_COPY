from getSelectedFilesFromExplorer import getSelectedFilesFromExplorer

selectedFiles = getSelectedFilesFromExplorer(infoAndError=False)

print("\n".join(selectedFiles), end="")
