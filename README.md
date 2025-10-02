# SSH_COPY - 1.1.0
Small collection of Python scripts to easily copy files between devices in the same local network. You must set up DHCP (static IP addresses) in your router settings otherwise the scripts won't work as their setup relies on hardcoded (by You) addresses in the shortcuts or wrapper scripts.

## Initial setup
Clone this repo to a folder named `SSH_COPY` or download contents of this repo and extract them to that folder.

Install required* Python packages:
```
pip install pywin32 termcolor paramiko
```
*\* - Don't install pywin32 on linux.*

## SSH_SEND.py
Copies selected files (and folders reqursively) in Windows Explorer or Nautilus to a folder on a remote machine.

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

Or open `SSH_COPY` folder in terrminal and run `bash setup-file.sh ssh-send.sh`. It should open the copied file in your default text editor so you can replace placeholders inside it.

Then in Nautilus you can select file(s) and/or folder(s) and right click and then `Scripts > ssh-send.sh`.

**Full help output:**

```
usage: SSH_SEND.py [-h] -u USERNAME -H HOSTNAME -p PASSWORD -r REMOTEFOLDER [-P PORT]
                   [-T TIMEOUT] [-t] [-0] [-c ENDCOMMAND] [-d]

options:
  -h, --help                        Show this help message and exit
  -u, --username USERNAME           Remote username
  -H, --hostname HOSTNAME           Remote host's address
  -p, --password PASSWORD           Remote password
  -r, --remote-folder REMOTEFOLDER  Remote folder's absolute path
  -P, --port PORT                   Remote port (default: 22)
  -T, --timeout TIMEOUT             TCP 3-way handshake timeout in seconds (default: 1)
  -t, --preserve-times              If set, modification times will be preserved
  -0, --zero-file                   Create a file named 0 at the end of transfer. Useful for
                                    file-watching scripts on the remote machine
  -c, --end-command ENDCOMMAND      Command to run on the remote machine after file transfer
  -d, --dont-close                  Don't auto-close console window at the end if no error
                                    occurred. You will have to close it manually or by pressing ENTER
```

**Example of successful output:**
```
1 file(s)/folder(s) selected
Attempting to connect to Hello@192.168.0.123 ...
Sending files:

ssh-send.sh

Successfully transferred 1 file(s)
```

## SSH_GET.py
It is similar to `SSH_SEND.py` but it copies selected files on the remote machine to a local folder.

Unfortunatelly it does not work :( - it is impossible at the moment to get the selected files from Explorer or Nautilus on a remote machine.

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

## SSH_SYNC.py
