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
from app import settings_manager

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

_OPEN_COUNT_INCREMENTED = False

def get_telemetry_state():
    """
    Retrieves or generates a persistent anonymous user ID and tracks open count.
    Stored in a location that survives application updates.
    """
    try:
        pass 
    except AttributeError:
        pass

    user_data_dir = path_utils.get_persistent_user_data_path()
    config_path = os.path.join(user_data_dir, "telemetry_id.json")
    
    uid = None
    open_count = 0
    
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                uid = data.get("uid")
                open_count = data.get("open_count", 0)
        except Exception:
            pass # corrupted file, generate new one
            
    if not uid:
        uid = str(uuid.uuid4())
        
    global _OPEN_COUNT_INCREMENTED
    
    should_save = False
    
    if not _OPEN_COUNT_INCREMENTED:
        open_count += 1
        _OPEN_COUNT_INCREMENTED = True
        should_save = True
        
    if should_save or not os.path.exists(config_path):
        try:
            if not os.path.exists(user_data_dir):
                os.makedirs(user_data_dir, exist_ok=True)
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump({"uid": uid, "open_count": open_count}, f)
        except Exception:
            pass # if we can't write, we proceed
            
    return {"uid": uid, "open_count": open_count}

def _send_heartbeat_thread(status, respect_optout=True):
    """
    Executes the network request in a background thread.

    respect_optout=True (normal heartbeats): if the user disabled telemetry, send nothing.
    respect_optout=False (forced events, e.g. an auto-update): the event is still sent, but
    when telemetry is OFF it carries a throwaway gibberish id instead of the persistent one —
    so the ping can't be tied back to the user and their stored id/open_count are untouched.
    """
    if not TELEMETRY_URL:
        return

    if TELEMETRY_ENV == "dev":
        return

    language = "ja" # Default
    telemetry_on = True

    # Check Opt-Out Setting
    try:
        settings = settings_manager.load_settings()
        telemetry_on = settings.get("telemetry_enabled", True)
        language = settings.get("target_language", "ja")
    except Exception:
        pass # proceed if settings fail to load (default is enabled)

    # A normal heartbeat honors the opt-out completely. A forced event ignores it but is
    # anonymized below.
    if respect_optout and not telemetry_on:
        return

    try:
        if telemetry_on:
            state = get_telemetry_state()
            uid = state["uid"]
            open_count = state["open_count"]
        else:
            # Opted out but this is a forced event: throwaway id, no persistent state touched.
            uid = "anon-" + uuid.uuid4().hex
            open_count = 0

        params = {
            "uid": uid,
            "version": __version__,
            "platform": sys.platform,
            "env": TELEMETRY_ENV,
            "lang": language,
            "status": status,
            "open_count": open_count
        }

        requests.get(TELEMETRY_URL, params=params, timeout=2)
    except Exception:
        # Fail silently
        pass

def init(status='Multilingual-beta'):
    """
    Initializes and sends the telemetry heartbeat.
    """
    # Only run if URL is configured
    if TELEMETRY_URL and TELEMETRY_ENV != "dev":
        thread = threading.Thread(target=_send_heartbeat_thread, args=(status,), daemon=True)
        thread.start()


def send_update_event(from_version):
    """Record a successful in-place auto-update, from->to, in the heartbeat's status field.

    Sent regardless of the telemetry opt-out (we always want to know an update landed), but
    when the user has telemetry OFF it goes out anonymized — a throwaway id, no persistent
    state — via respect_optout=False. Still honors the dev-env skip and fails silently. The
    'to' version is the running __version__ (the code is already the new build when this fires).
    """
    if TELEMETRY_URL and TELEMETRY_ENV != "dev":
        status = f"Updated {from_version} -> {__version__}"
        thread = threading.Thread(
            target=_send_heartbeat_thread, args=(status,),
            kwargs={"respect_optout": False}, daemon=True)
        thread.start()
