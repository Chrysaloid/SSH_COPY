@echo off

@REM cd /d "<path_to_SSH_COPY_folder>"

@REM This way you can (un)comment out individual lines and move arguments around easily
set args=
set args=%args% --username Test
set args=%args% --hostname 192.168.0.121
set args=%args% --remote-os win
set args=%args% --cache-directory-listings
set args=%args% --operation "G:/Test/Nowy folder/Source" remote "G:/Test/Nowy folder/Destination" remote sync "*.txt/true" false

python SSH_SYNC_BULK.py %args%
