# SSH_COPY - 1.4.0
Small collection of Python scripts to easily copy files between devices in the same local network. You must set up DHCP (static IP addresses) in your router settings otherwise the scripts won't work as their setup relies on hardcoded (by You) addresses in the shortcuts or wrapper scripts.

## Initial setup
Clone this repo to a folder named `SSH_COPY` or download contents of this repo and extract them to that folder.

Install required* Python packages:
```
pip install termcolor paramiko pywin32
```
*\* - Don't install pywin32 on linux.*

## SSH_SEND.py
Copies selected files (and folders recursively) in Windows Explorer or Nautilus to a folder on a remote machine.

It will open a terminal window that will automatically close if no errors occurred. If an error occurred the window will stay open so you can inspect the error message.

**Basic usage on Windows:**

Create shortcut with the following content (with placeholders replaced) in *Target*:

Using Windows Terminal (recommended):
```
wt --window new cmd /K @echo off && python SSH_SEND.py -u USERNAME -H HOSTNAME -p PASSWORD -r "REMOTEFOLDER" && exit
```
Using cmd.exe:
```
cmd /K @echo off && python SSH_SEND.py -u USERNAME -H HOSTNAME -p PASSWORD -r "REMOTEFOLDER" && exit
```
Put absolute path to `SSH_COPY` folder in the *Start in* field.

You can rename the shortcut and change its icon if you want. It's convenient  to put it in `C:\ProgramData\Microsoft\Windows\Start Menu\Programs` folder (or its subfolder) - that way it will appear in *All applications* and you can pin it to the Start Menu for quick access.

**Example:**

*Target*:
```
wt --window new cmd /K @echo off && python SSH_SEND.py -u Hello -H 192.168.0.123 -p world -r "C:\Users\Hello\Downloads" && exit
```
*Start in*:
```
C:\PythonScripts\SSH_COPY
```

**Basic usage on Linux (with Nautilus):**

We provide guide for Nautilus. Set up on other file managers should be similar.

Copy `ssh-send.sh` to `~/.local/share/nautilus/scripts` and replace placeholders in it.

Or open `SSH_COPY` folder in terminal and run `bash setup-file.sh ssh-send.sh`. It should open the copied file in your default text editor so you can replace placeholders inside it.

Then in Nautilus you can select file(s) and/or folder(s) and right click and then `Scripts > ssh-send.sh`.

**Full help output:**

```
usage: SSH_SEND.py [-h] -u USERNAME -H HOSTNAME -p PASSWORD -r REMOTEFOLDER [-P PORT] [-T TIMEOUT]
                   [-t] [-0] [-c ENDCOMMAND] [-d]

Copies selected files (and folders recursively) in Windows Explorer or Nautilus to a folder on a
remote machine.

Required arguments:
  -u, --username USERNAME     Remote username
  -H, --hostname HOSTNAME     Remote host's address
  -p, --password PASSWORD     Remote password
  -r, --remote-folder REMOTEFOLDER
                              Remote folder's absolute path

Optional arguments:
  -h, --help                  show this help message and exit
  -P, --port PORT             Remote port (default: 22)
  -T, --timeout TIMEOUT       TCP 3-way handshake timeout in seconds (default: 1)
  -t, --preserve-times        If set, modification times will be preserved
  -0, --zero-file             Create a file named 0 at the end of transfer. Useful for file-watching
                              scripts on the remote machine
  -c, --end-command ENDCOMMAND
                              Command to run on the remote machine after file transfer
  -d, --dont-close            Don't auto-close console window at the end if no error occurred. You
                              will have to close it manually or by pressing ENTER
```

**Example of successful output:**
```
1 file(s)/folder(s) selected
Attempting to connect to Hello@192.168.0.123 ...
Sending files:

SSH_SEND.py

Successfully sent 1 file(s)

Execution time: 0.169 s
```

## SSH_SYNC.py
Copy or synchronize files between folders on remote or local machines.

**This script can work fully locally** if you omit the SSH authorization details. Then the `-r/--remote-folder` argument ACTUALLY refers to a local folder and only the order of folder arguments matters.

The first folder argument becomes the source folder and the second - the destination folder. So when the source folder is remote files will be downloaded and when the destination is remote the files will be uploaded.

**File transfer only occurs if the destination does not have a source file or if the destination is older than the source.**

The `copy` mode is similar to other tools like [`rsync`](https://download.samba.org/pub/rsync/rsync.1) or [`scp`](https://manpages.debian.org/stretch/openssh-client/scp.1.en.html). The new and unique functionality it provides comes from the `--newer-than-newest-*` options described below.

The `sync` mode is something I couldn't achieve using other tools (that's why I made this script). It aims to achieve a similar effects as if both folders where the same folder in the cloud storage but without using cloud storage and instead using SSH (or not if working fully locally). Simplified it works like this:

1. Get list of files/folders in both folders.
2. Find the newest file that is present in both folders. That pair of files must have the same name and the same modification date.
3. Files newer than that date in one folder are copied over to the other folder if the other folder doesn't have those files or it has older versions.
4. Files older than that date in one folder that are not present in the other folder are deleted.
5. Optionally repeat previous actions recursively.

Good example usage for the `sync` mode is maintaining a synchronized music library on 2 devices (let's call them a stationary **PC** and a **laptop**). Let's say you listen to music sometimes on you PC and sometimes on your laptop. When you do, you like to discover new music (in any way) then you'd like to download that music to your device. If you did that separately on the PC and on the laptop, your laptop now has music files that your PC doesn't and vice versa. Let's say that simultaneously you deleted an old track, that you got bored with, on your laptop. Now your PC has new files, your laptop has new files and it also has a deleted file. Running this script with `--mode sync` will delete the undeleted file on your PC and copy new files both ways. Now both folders have the same contents.

**Basic usage:**

Since you'd be running this not too often and the setup can get pretty big I suggest creating a script for this command. Simple but easily expandable example scripts were supplied: `ssh-sync.bat` for Windows and `ssh-sync.sh` for Linux. Main advantage of the format of those files (so 1 argument per line) is that if you open that file in an IDE, you can do many things with the lines easily: comment them out, uncomment them, move them around, delete them.

**Full help output:**

```
usage: SSH_SYNC.py [-h] -l ABSOLUTE_PATH -r ABSOLUTE_PATH [-i [PATTERN_1 [PATTERN_2 ...]]]
                   [-e [PATTERN_1 [PATTERN_2 ...]]] [-c [PATTERN_1 [PATTERN_2 ...]]]
                   [-a [PATTERN_1 [PATTERN_2 ...]]] [-I [PATTERN_1 [PATTERN_2 ...]]]
                   [-E [PATTERN_1 [PATTERN_2 ...]]] [-C [PATTERN_1 [PATTERN_2 ...]]]
                   [-A [PATTERN_1 [PATTERN_2 ...]]] [-u USERNAME] [-H HOSTNAME] [-p PASSWORD]
                   [-y KEY_FILENAME [KEY_FILENAME ...]] [-P PORT] [-T SECONDS] [-n DATE] [-f DATE]
                   [-R [MAX_RECURSION_DEPTH]] [-S] [-x] [-v] [-s] [-t] [-B] [-d] [-b] [-k] [-K] [-L]
                   [-G] [-m {sync,copy}] [-F] [-N] [-M] [-D] [-g [FORMAT]] [-j]

Copy or sync files between folders on remote or local machines

Required arguments:
  -l, --local-folder ABSOLUTE_PATH
                              Local folder's absolute path
  -r, --remote-folder ABSOLUTE_PATH
                              Remote (or local) folder's absolute path

Optional common arguments:
  -h, --help                  show this help message and exit
  -i, --include-files [PATTERN_1 [PATTERN_2 ...]]
                              Glob patterns for files to include in copy/sync
  -e, --exclude-files [PATTERN_1 [PATTERN_2 ...]]
                              Glob patterns for files to exclude in copy/sync
  -c, --include-files-case [PATTERN_1 [PATTERN_2 ...]]
                              Glob patterns for files to include in copy/sync (case-sensitive)
  -a, --exclude-files-case [PATTERN_1 [PATTERN_2 ...]]
                              Glob patterns for files to exclude in copy/sync (case-sensitive)
  -I, --include-folders [PATTERN_1 [PATTERN_2 ...]]
                              Glob patterns for folders to include in copy/sync
  -E, --exclude-folders [PATTERN_1 [PATTERN_2 ...]]
                              Glob patterns for folders to exclude in copy/sync
  -C, --include-folders-case [PATTERN_1 [PATTERN_2 ...]]
                              Glob patterns for folders to include in copy/sync (case-sensitive)
  -A, --exclude-folders-case [PATTERN_1 [PATTERN_2 ...]]
                              Glob patterns for folders to exclude in copy/sync (case-sensitive)
  -u, --username USERNAME     Remote username
  -H, --hostname HOSTNAME     Remote host's address
  -p, --password PASSWORD     Remote password
  -y, --key-filename KEY_FILENAME [KEY_FILENAME ...]
                              Path to local OpenSSH private-key
  -P, --port PORT             Remote port (default: 22)
  -T, --timeout SECONDS       TCP 3-way handshake timeout in seconds (default: 5)
  -n, --files-newer-than DATE
                              Copy/Sync only files newer then this date
  -f, --folders-newer-than DATE
                              Copy/Sync only folders newer then this date
  -R, --recursive [MAX_RECURSION_DEPTH]
                              Recurse into subdirectories. Optionaly takes max recursion depth as
                              parameter. The source and destination folders are considered as depth
                              == 0 so specifying "--recursive 0" is the same as not specyfying it at
                              all
  -S, --create-dest-folder    If destination folder doesn't exists, create it and all its parents
                              (like mkdir (-p on Linux)). If not set terminate the script if the
                              folder doesn't exist
  -x, --create-max-rec-folders
                              Create empty folders at max recursion depth
  -v, --verbose               Print verbose information. Good for debugging
  -s, --silent                Print only errors
  -t, --dont-preserve-times   If set, modification times will not be preserved and instead
                              files/folders will have time of copy/sync set as their modification
                              time
  -B, --dont-preserve-permissions
                              If set, permissions will not be preserved and instead files/folders
                              will have default permissions set
  -d, --dont-close            Don't auto-close console window at the end if no error occurred. You
                              will have to close it manually or by pressing ENTER
  -b, --fast-remote-listdir-attr
                              If you copy/sync folder(s) containing more than 5000 entries from/to
                              remote location this may be faster. Requires Python 3 on remote host
  -k, --listdir-attr-fallback
                              Instead of terminating the script if remote does not have Python 3,
                              fall back to "slow" listdir-attr. Only applicable if -b/--fast-remote-
                              listdir-attr was set
  -K, --end-on-inaccessible-entry
                              Terminate the script if it does not have enough perrmisions to access
                              any encountered file/folder (local or remote). If not set ignore such
                              cases but print a warning
  -L, --end-on-file-onto-folder
                              Terminate the script if a file is to be copied onto a folder and vice
                              versa. If not set ignore such cases but print a warning
  -G, --sort-entries          Sort files/folders by name alphabetically before copying. Except for
                              making the logs look more familiar it does not have much other use
                              cases
  -m, --mode {sync,copy}      One of values: sync,copy (default: copy)

COPY mode arguments:
  -F, --force                 Force copying of source files even if they are older then destination
                              files
  -N, --newer-than-newest-file
                              Copy only files newer then the newest file in the destination folder
  -M, --newer-than-newest-folder
                              Copy only files newer then the newest folder in the destination folder
  -D, --dont-filter-dest      Don't filter the destination files/folders WHEN SEARCHING FOR THE
                              NEWEST FILE

SYNC mode arguments:
  -g, --print-common-date [FORMAT]
                              Before printing file transfers print the detected newest common date.
                              Optionaly take date format string as parameter (default: "%Y-%m-%d
                              %H:%M - {rel}")
  -j, --common-date-from-folders
                              Include folders when searching for newest common date
```

**Arguments that need more explanation:**

- `--include-*` and `--exclude-*` arguments - They allow for fine-grained file/folder selection. They use only the file/folder name for matching. They use Unix filename pattern matching provided by the [`fnmatch`](https://docs.python.org/3/library/fnmatch.html) module. You can pass multiple parameters at a time and you can specify those arguments multiple times. Each of these will be checked in order they were passed and first one that matches the given filename will take effect. If the first argument of this kind is a `--include-*` argument by default all files will be excluded. Analogically if the first argument of this kind is a `--exclude-*` argument by default all files will be included. When none of those arguments is specified all files are included by default. I made it work that way as I think it's quite intuitive - if you just `--include-*` something you probably want to just copy that and nothing else and if you just `--exclude-*` something you probably want to copy everything except that. Some examples:

	- `--include-files *.mp3` - Only copy MP3 files and nothing else.

	- `--exclude-files  bad-song-1.mp3  bad-song-2.mp3  --include-files  *.mp3  *.flac  *.m4a  --exclude-files *` or `--include-files  --exclude-files  bad-song-1.mp3  bad-song-2.mp3  --include-files  *.mp3  *.flac  *.m4a` - only copy audio files and nothing else but exclude some specific files.

		- If you removed the `--exclude-files *` part at the end from the first example above or the `--include-files` part at the beginning from the seconds example it would not work as expected because only specifying `--exclude-files  bad-song-1.mp3  bad-song-2.mp3  --include-files  *.mp3  *.flac  *.m4a` would include all files by default as an `--exclude-*` argument is first. Similarly doing `--include-files  *.mp3  *.flac  *.m4a  --exclude-files  bad-song-1.mp3  bad-song-2.mp3` would include the bad songs as `*.mp3` would match them first.

- `--dont-preserve-permissions` - Preserving permissions is only sensible when copying files between Unix machines as Windows has different permission system, incompatible with Unix so this argument has effect only when both source and destination folders are on Unix machine(s).

- `--fast-remote-listdir-attr` - This argument invokes a small persistent remote Python script (which is closed when this script ends) that uses [`os.scandir`](https://docs.python.org/3/library/os.html#os.scandir) and `stdin` and `stdout` streams to get the list of files with attributes in the remote folder faster than the paramiko's [`sftp.listdir_iter`](https://docs.paramiko.org/en/latest/api/sftp.html#paramiko.sftp_client.SFTPClient.listdir_iter). After some testing using the machines I had at hand (Windows PC, Windows Laptop, Android phone with [Termux](https://termux.dev/en/), old Linux Laptop) I came up with conclusion that in any mode if at least 1 remote folder that will be included in a copy has at least 5000 entries then `--fast-remote-listdir-attr` will make the whole script a bit faster - in a simple test with 5000 files when none of them were copied (because source and destination where the same folder) when connected to myself in sync mode **without this argument the `Execution time` was ~600 ms** and **with this argument set the time dropped to ~350 ms**. If any files would be copied, you wouldn't notice the difference this argument makes but you can experiment as `Execution time` of the whole script is always measured and displayed.

- `--newer-than-newest-*` arguments - This has a niche use case when you want to periodically download files from a server but after the first download you want to delete old files for any reason (i.e. you don't won't them because they are big). After the copy you and the server have the same newest files but you are missing the older ones. With this argument set next time you copy only newly added files on the server will be copied and the older files you deleted locally will not be copied. If you specify both the file and folder version of this argument the search is performed on both files and folders and the newest entry's date is chosen.

- `--dont-filter-dest` - By default destination is filtered using the patterns specified by `--include-*` and `--exclude-*` arguments and `--*-newer-than` arguments WHEN SEARCHING FOR THE NEWEST FILE. With this argument set that filtering is not performed. Setting this argument, when both `--newer-than-newest-*` arguments are unset, has no effect.

- `--print-common-date` - The FORMAT first goes trough [datetime.strftime](https://docs.python.org/3/library/datetime.html#datetime.datetime.strftime) so you'd like to look at the [format codes](https://docs.python.org/3/library/datetime.html#format-codes). Then the `{rel}` gets replaced with the relative time to the date.

- `--common-date-from-folders` - By default only files in the respective folders are searched for the newest common date. That is to prevent changes in subfolders from affecting that date in the given folder as **creation, deletion or renaming of a file in a subfolder will update it's modification date**. This argument makes **included** subfolders' modification dates to be considered as well. If recursion is disabled this argument has no effect.

- `--key-filename` - Works the same as the [`SSHClient.connect()`](https://docs.paramiko.org/en/stable/api/client.html#paramiko.client.SSHClient.connect)'s `key_filename` parameter so it *"may contain OpenSSH public certificate paths as well as regular private-key paths; when files ending in -cert.pub are found, they are assumed to match a private key, and both components will be loaded. (The private key itself does not need to be listed in key_filename for this to occur - just the certificate)"*. You can pass multiple values split among multpiple arguments i.e.:
	- `--key-filename /path/one /path/two --key-filename /path/three`

**Example of successful output in `copy` mode:**

```
Attempting to connect to Hello@192.168.0.123 ...
Copying from local to remote
Source      folder: G:/Test/Source
Destination folder: G:/Test/Destination
Copying files:

/SSH_SYNC.py

Execution time: 0.171 s
```

**Example of successful output in `sync` mode:**

```
Attempting to connect to Hello@192.168.0.123 ...
Syncing from local to remote
Source      folder: G:/Test/Source
Destination folder: G:/Test/Destination
Syncing files:

source -> destination: /SSH_SYNC.py

Execution time: 0.156 s
```

## ~~SSH_GET.py~~
It is similar to `SSH_SEND.py` but it copies selected files on the remote machine to a local folder.

Unfortunately it does not work :( - it is impossible at the moment to get the selected files from Explorer or Nautilus on a remote machine.

But we leave it here in case if we solve the above problem.

Setup and usage is very similar `SSH_SEND.py` so we only put the help print here.

**Full help output:**

```
usage: SSH_GET.py [-h] -u USERNAME -H HOSTNAME -p PASSWORD -l LOCALFOLDER
                  -r REMOTEGETFILESSCRIPT [-P PORT] [-T TIMEOUT] [-t] [-d]

options:
  -h, --help                      Show this help message and exit
  -u, --username USERNAME         Remote username
  -H, --hostname HOSTNAME         Remote host's address
  -p, --password PASSWORD         Remote password
  -l, --local-folder LOCALFOLDER  Local folder's absolute path
  -r, --remote-get-files-script REMOTEGETFILESSCRIPT
                                  Remote getSelectedFilesFromExplorerRecurseStdOut.py absolute path
  -P, --port PORT                 Remote port (default: 22)
  -T, --timeout TIMEOUT           TCP 3-way handshake timeout in seconds (default: 1)
  -t, --preserve-times            If set, modification times will be preserved
  -d, --dont-close                Don't auto-close console window at the end if no error
                                  occurred. You will have to close it manually or by pressing ENTER
```
