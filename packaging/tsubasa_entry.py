"""tsubasa.exe's entry (T1 B, 2026-10-21): tsubasa's own console script, `tsubasa = tsubasa.cli:main`, written out —
PyInstaller freezes scripts, not entry points. The same one line as tsubasa's own packaging/entry_cli.py: the program is
tsubasa's, built from the tsubasa-sync requirements.txt pins. Nothing of Surasura's imports this file or tsubasa (K1):
Connect runs tsubasa.exe as its own program."""
import sys

from tsubasa.cli import main

if __name__ == "__main__":
    sys.exit(main())
