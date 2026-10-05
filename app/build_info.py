"""What kind of build this is. `package_app.py --release` sets RELEASE_BUILD to True for the freeze (and puts the file
back after), so it is True only inside a release's Surasura.exe. A release build ignores every test-only override —
today the update check's local folder (`update_checker.UPDATE_SOURCE_ENV`)."""
RELEASE_BUILD = False
