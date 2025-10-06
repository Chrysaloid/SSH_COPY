#!/bin/bash

cd "<path_to_SSH_COPY_folder>"

# This way you can (un)comment out individual lines and move arguments around easily
args=(
--username Hello
--hostname 192.168.0.123
-p world
--local-folder "/Test/Source"
--remote-folder "/Test/Destination"
--recursive
--mode sync
--print-common-date

# --exclude-files  bad-song-1.mp3  bad-song-2.mp3
# --include-files  *.mp3  *.flac  *.m4a
# --exclude-files  *

# --fast-remote-listdir-attr
# --verbose
)

python SSH_SYNC.py "${args[@]}"
