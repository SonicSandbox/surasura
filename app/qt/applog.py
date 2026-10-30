"""The window's log lines, in the app's log (`<local data>/logs/app_debug_log.txt`, as `app_entry.log_error` writes it:
`path_utils.write_app_log`, each line stamped). Logging never stops the window."""
from app import path_utils


def log(area, msg):
    path_utils.write_app_log(f"window ({area}): {msg}")
