#!/bin/bash
set -e # Exit immediately on error

folder=~/.local/share/nautilus/scripts
mkdir -p "$folder"
chmod +x $1                                               # Make the file executable
cp $1 "$folder/"                                          # Copy it
sed -i "s/<path_to_SSH_COPY_folder>/$(pwd)/" "$folder/$1" # Replace placeholder for folder path
xdg-open "$folder/$1"                                     # Open the copy
