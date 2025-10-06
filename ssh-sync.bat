@echo off

cd /d "<path_to_SSH_COPY_folder>"

@REM This way you can (un)comment out individual lines and move arguments around easily
set args=
set args=%args% --username Hello
set args=%args% --hostname 192.168.0.123
set args=%args% -p world
set args=%args% --local-folder "C:\Test\Source"
set args=%args% --remote-folder "C:\Test\Destination"
set args=%args% --recursive
set args=%args% --mode sync
set args=%args% --print-common-date

@REM set args=%args% --exclude-files  bad-song-1.mp3  bad-song-2.mp3
@REM set args=%args% --include-files  *.mp3  *.flac  *.m4a
@REM set args=%args% --exclude-files  *

@REM set args=%args% --fast-remote-listdir-attr
@REM set args=%args% --verbose

python SSH_SYNC.py %args%
