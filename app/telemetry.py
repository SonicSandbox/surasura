import os
import sys
import uuid
import json
import logging
import threading
import requests
from dotenv import load_dotenv
from app import path_utils
from app import __version__

# Load environment variables from .env file
# If frozen, look in sys._MEIPASS (where PyInstaller unpacks resources).
# If running from source, load_dotenv() finds it automatically.
# If frozen, look in sys._MEIPASS (where PyInstaller unpacks resources).
# If running from source, load_dotenv() finds it automatically.
try:
    if getattr(sys, 'frozen', False):
        dotenv_path = os.path.join(sys._MEIPASS, '.env')
        if os.path.exists(dotenv_path):
            load_dotenv(dotenv_path)
    else:
        load_dotenv()
except Exception:
    # If .env is missing or fails to load, we just proceed with default env vars (or None)
    pass

TELEMETRY_URL = os.getenv("TELEMETRY_URL")
TELEMETRY_ENV = os.getenv("TELEMETRY_ENV", "production")

def get_telemetry_id():
    """
    Retrieves or generates a persistent anonymous user ID.
    Stored in a location that survives application updates.
    """
    try:
        # persistent_dir = path_utils.get_persistent_user_data_path()
        # For now, we'll implement a local version of this logic here if path_utils
        # hasn't been updated yet, but the plan says to update path_utils first.
        # Let's assume path_utils will have get_persistent_user_data_path.
        # If not, we'll need to implement it in path_utils.
        
        # Checking if path_utils has the function. If not, we will need to add it.
        # But since I am writing this file first, I should probably rely on path_utils
        # to be updated soon.
        pass 
    except AttributeError:
        # Fallback if path_utils isn't updated yet (during dev/testing)
        pass

    user_data_dir = path_utils.get_persistent_user_data_path()
    config_path = os.path.join(user_data_dir, "telemetry_id.json")
    
    uid = None
    
    # customized logic to migrate from old location if necessary?
    # No, this is a new feature.
    
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                uid = data.get("uid")
        except Exception:
            pass # corrupted file, generate new one
            
    if not uid:
        uid = str(uuid.uuid4())
        try:
            if not os.path.exists(user_data_dir):
                os.makedirs(user_data_dir, exist_ok=True)
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump({"uid": uid}, f)
        except Exception:
            pass # if we can't write, we simply won't persist.
            
    return uid

def _send_heartbeat_thread():
    """
    Executes the network request in a background thread.
    """
    if not TELEMETRY_URL:
        return
        
    if TELEMETRY_ENV == "dev":
        return

    # Check Opt-Out Setting
    try:
        settings_path = path_utils.get_user_file("settings.json")
        if os.path.exists(settings_path):
            with open(settings_path, "r", encoding="utf-8") as f:
                settings = json.load(f)
                if not settings.get("telemetry_enabled", True):
                    return
    except Exception:
        pass # proceed if settings fail to load (default is enabled)

    try:
        uid = get_telemetry_id()
        platform = sys.platform
        
        params = {
            "uid": uid,
            "version": __version__,
            "platform": platform,
            "env": TELEMETRY_ENV
        }
        
        requests.get(TELEMETRY_URL, params=params, timeout=2)
    except Exception:
        # Fail silently
        pass

def init():
    """
    Initializes and sends the telemetry heartbeat.
    """
    # Only run if URL is configured
    if TELEMETRY_URL and TELEMETRY_ENV != "dev":
        thread = threading.Thread(target=_send_heartbeat_thread, daemon=True)
        thread.start()
