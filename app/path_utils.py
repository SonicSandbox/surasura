import os
import sys
import shutil

def is_frozen():
    """Check if the application is running in a frozen (packaged) environment."""
    return getattr(sys, 'frozen', False)

def get_base_path():
    """
    Get the base directory for retrieving RESOURCES (templates, bundled scripts).
    If frozen: return sys._MEIPASS (temp dir where resources are unpacked).
    If source: return the root of the project (one level up from app/).
    """
    if is_frozen():
        return sys._MEIPASS
    else:
        # Assumes this file is in app/path_utils.py, so root is ../
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def get_user_data_path():
    """
    Get the directory for USER DATA (inputs, outputs, settings).
    If frozen: return the directory containing the executable.
    If source: return the root of the project.
    """
    if is_frozen():
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def get_persistent_user_data_path():
    """
    Get the directory for PERSISTENT USER DATA (e.g. telemetry ID).
    This path should survive application updates/reinstalls.
    Windows: %APPDATA%/SonicSandbox/Surasura/
    Linux/Mac: ~/.local/share/SonicSandbox/Surasura/
    """
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        if not base:
            base = os.path.expanduser("~")
        path = os.path.join(base, "SonicSandbox", "Surasura")
    else:
        # XDG Base Directory Specification fallback
        base = os.environ.get("XDG_DATA_HOME")
        if not base:
             base = os.path.join(os.path.expanduser("~"), ".local", "share")
        path = os.path.join(base, "SonicSandbox", "Surasura")
        
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)
        
    return path

def get_resource(path):
    """Resolve a resource path relative to the bundle."""
    return os.path.join(get_base_path(), path)

def get_user_file(path):
    """Resolve a user file path relative to the executable location."""
    return os.path.join(get_user_data_path(), path)

def get_data_path(language=None):
    """
    Get the data directory, optionally for a specific language.
    Process: data/<language>/
    """
    base = get_user_file("data")
    if language:
        return os.path.join(base, language)
    return base

def get_user_files_path(language=None):
    """
    Get the User Files directory, optionally for a specific language.
    Process: User Files/<language>/
    """
    base = get_user_file("User Files")
    if language:
        return os.path.join(base, language)
    return base

def get_icon_path():
    """Returns the path to the application icon."""
    return get_resource(os.path.join("app", "assets", "images", "app_icon.png"))

def get_ico_path():
    """Returns the path to the application .ico file (Windows)."""
    return get_resource(os.path.join("app", "assets", "images", "app_icon.ico"))

def ensure_data_setup(language=None):
    """
    Ensures that the data folders exist and copies samples into them if they are empty.
    If language is provided, setup inside data/<language>/ and User Files/<language>/
    """
    # 1. Determine Paths
    data_path = get_data_path(language)
    user_files_dir = get_user_files_path(language)
    
    samples_path = get_resource("samples")
    
    subfolders = ["HighPriority", "LowPriority", "GoalContent", "Processed"]
    
    # 2. Ensure base data folder exists
    if not os.path.exists(data_path):
        os.makedirs(data_path, exist_ok=True)
        
    # 3. Setup subfolders (Copy samples if destination is empty)
    for folder in subfolders:
        target_dir = os.path.join(data_path, folder)
        
        # Create folder if it doesn't exist
        if not os.path.exists(target_dir):
            os.makedirs(target_dir, exist_ok=True)
            
        # Determine source samples path
        # Default to 'ja' if language is None or 'ja', otherwise try to use the language folder
        sample_lang = language if language else 'ja'
        source_dir = os.path.join(samples_path, sample_lang, folder)
        
        # If folder is empty and source exists, copy samples
        if os.path.exists(target_dir) and not os.listdir(target_dir):
            if os.path.exists(source_dir):
                for item in os.listdir(source_dir):
                    s = os.path.join(source_dir, item)
                    d = os.path.join(target_dir, item)
                    if os.path.isfile(s):
                        shutil.copy2(s, d)
                    elif os.path.isdir(s):
                        shutil.copytree(s, d, dirs_exist_ok=True)

    # 4. Ensure User Files folder exists
    if not os.path.exists(user_files_dir):
        os.makedirs(user_files_dir, exist_ok=True)
        
    # 5. Create Blacklist/IgnoreList if they don't exist
    for list_name in ["Blacklist.txt", "IgnoreList.txt"]:
        list_path = os.path.join(user_files_dir, list_name)
        if not os.path.exists(list_path):
            try:
                with open(list_path, "w", encoding="utf-8") as f:
                    if list_name == "Blacklist.txt":
                        f.write("# Global Blacklist\n" if not language else f"# {language} Blacklist\n")
                    else:
                        f.write("# Add words to ignore here (one per line)\n")
            except Exception as e:
                print(f"Warning: Could not create {list_name}: {e}")
