# SSH_COPY
Small collection of Python scripts to easily copy files between devices in the same local network. You must set up DHCP (static IP addresses) in your router settings otherwise the scripts won't work as their setup relies on hardcoded (by You) addresses in the shortcuts or wrapper scripts.

## Initial setup
Clone this repo to a folder named `SSH_COPY` or download contents of this repo and extract them to that folder.

Install required Python packages:
```
pip install pywin32 termcolor paramiko
```

## SSH_SEND.py
Copies selected files (and folders reqursively) in Windows Explorer or Nautilus to a folder on a remote machine.

It will open a terminal window that will automatically close if no errors occurred. If an error occured the window will stay open so you can inspect the error message.

**Usage on Windows:**

Create shortcut with the following content (with placeholders replaced) in *Target*:

Using Windows Terminal (recommended):
```
wt --window new cmd /K @echo off && python SSH_SEND.py <username> <hostname> <password> "<remoteFolderAbsPath>" && exit
```
Using cmd.exe:
```
cmd /K @echo off && python SSH_SEND.py <username> <hostname> <password> "<remoteFolderAbsPath>" && exit
```
Put absolute path to `SSH_COPY` folder in the *Start in* field.

You can rename the shortcut and change its icon if you want. It's convinient to put it in `C:\ProgramData\Microsoft\Windows\Start Menu\Programs` folder (or its subfolder) - that way it will appear in *All applications* and you can pin it to the Start Menu for quick access.

**Example:**

*Target*:
```
wt --window new cmd /K @echo off && python SSH_SEND.py Hello 192.168.0.123 world "C:\Users\Hello\Downloads" && exit
```
*Start in*:
```
C:\PythonScripts\SSH_COPY
```

**Usage on Linux (with Nautilus):**

We provide guide for Nautilus. Set up on other file managers should be similar.

Copy `ssh-send.sh` to `~/.local/share/nautilus/scripts` and replace placeholders in it.

Or open `SSH_COPY` folder in terrminal and run `bash setup-file.sh ssh-send.sh` (I recommend you inspect it before you run it). It should open the copied file in your default text editor so you can replace placeholders inside it.

Then in Nautilus you can select file(s) and/or folder(s) and right click and then `Scripts > ssh-send.sh`.

**Example of successful output:**
```
1 file(s)/folder(s) selected
Attempting to connect to Hello@192.168.0.123 ...
Transfering files:

ssh-send.sh

Successfully transferred 1 file(s)
```
