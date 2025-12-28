import json
import os

from .getSelectedFilesFromExplorer import getSelectedFilesFromExplorer

selectedFiles = getSelectedFilesFromExplorer(infoAndError=False)

if not selectedFiles: # finish early if there were no files selected
	exit(69) # (¬‿¬)

baseFolder = os.path.dirname(selectedFiles[0])
subFolders = []
files = []

def getFileStructureRecursively(fileOrDirPath: str):
	if os.path.isfile(fileOrDirPath):
		files.append(os.path.relpath(fileOrDirPath, baseFolder).replace("\\", "/"))
	elif os.path.isdir(fileOrDirPath):
		subFolders.append(os.path.relpath(fileOrDirPath, baseFolder).replace("\\", "/"))
		for item in os.listdir(fileOrDirPath):
			getFileStructureRecursively(os.path.join(fileOrDirPath, item).replace("\\", "/"))

for fileOrDirPath in selectedFiles:
	getFileStructureRecursively(fileOrDirPath)

print(
	json.dumps(
		{
			"baseFolder": baseFolder,
			"subFolders": subFolders,
			"files": files,
		},
		ensure_ascii=False,
		check_circular=False,
		indent=None,
		separators=(",",":")
	),
	end=""
)
