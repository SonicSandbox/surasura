"""The window's log lines, in the app's log (`<local data>/logs/app_debug_log.txt`, as `app_entry.log_error` writes it).
Logging never stops the window."""
import os

from app import path_utils


def log(area, msg):
    try:
        folder = os.path.join(path_utils.get_local_data_path(), "logs")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "app_debug_log.txt"), "a", encoding="utf-8") as f:
            f.write(f"window ({area}): {msg}\n")
    except Exception:
        pass
