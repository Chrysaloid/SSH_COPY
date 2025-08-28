#!/bin/bash
gnome-terminal -- bash -c "cd \"<path_to_SSH_COPY_folder>\" && echo \"$NAUTILUS_SCRIPT_SELECTED_FILE_PATHS\" | python SSH_SEND.py -u USERNAME -H HOSTNAME -p PASSWORD -r \"REMOTEFOLDER\" || bash"
