from pathlib import Path; __package__ = __package__ or Path(__file__).resolve().parent.name # To be able to use relative imports when run directly - never override a __package__ Python already set (see README)

import json
import os

from .get_selected_files_from_explorer import get_selected_files_from_explorer

selected_files = get_selected_files_from_explorer(info_and_error=False)

if not selected_files: # finish early if there were no files selected
	exit(69) # (¬‿¬)

base_folder = os.path.dirname(selected_files[0])
sub_folders = []
files = []

def get_file_structure_recursively(file_or_dir_path: str):
	if os.path.isfile(file_or_dir_path):
		files.append(os.path.relpath(file_or_dir_path, base_folder).replace("\\", "/"))
	elif os.path.isdir(file_or_dir_path):
		sub_folders.append(os.path.relpath(file_or_dir_path, base_folder).replace("\\", "/"))
		for item in os.listdir(file_or_dir_path):
			get_file_structure_recursively(os.path.join(file_or_dir_path, item).replace("\\", "/"))

for file_or_dir_path in selected_files:
	get_file_structure_recursively(file_or_dir_path)

print(
	json.dumps(
		{
			"baseFolder": base_folder,
			"subFolders": sub_folders,
			"files": files,
		},
		ensure_ascii=False,
		check_circular=False,
		indent=None,
		separators=(",",":")
	),
	end=""
)
