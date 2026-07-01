#!/bin/bash

# cd "<path_to_SSH_COPY_folder>"

# This way you can (un)comment out individual lines and move arguments around easily
args=(
--username Test
--hostname 192.168.0.121
--remote-os win
--cache-directory-listings
--operation "G:/Test/Nowy folder/Source" remote "G:/Test/Nowy folder/Destination" remote sync "*.txt/true" false
)

python SSH_SYNC_BULK.py "${args[@]}"
