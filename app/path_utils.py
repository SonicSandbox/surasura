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

def get_resource(path):
    """Resolve a resource path relative to the bundle."""
    return os.path.join(get_base_path(), path)

def get_user_file(path):
    """Resolve a user file path relative to the executable location."""
    return os.path.join(get_user_data_path(), path)

def get_icon_path():
    """Returns the path to the application icon."""
    return get_resource(os.path.join("app", "assets", "images", "app_icon.png"))

def get_ico_path():
    """Returns the path to the application .ico file (Windows)."""
    return get_resource(os.path.join("app", "assets", "images", "app_icon.ico"))

def ensure_data_setup():
    """
    Ensures that the data folders exist and copies samples into them if they are empty.
    """
    data_path = get_user_file("data")
    samples_path = get_resource("samples")
    
    subfolders = ["HighPriority", "LowPriority", "GoalContent"]
    
    # 1. Ensure base data folder exists
    if not os.path.exists(data_path):
        os.makedirs(data_path, exist_ok=True)
        
    # 2. Setup subfolders
    for folder in subfolders:
        target_dir = os.path.join(data_path, folder)
        source_dir = os.path.join(samples_path, folder)
        
        # Create folder if it doesn't exist
        if not os.path.exists(target_dir):
            os.makedirs(target_dir, exist_ok=True)
            
        # If folder is empty, copy samples
        if os.path.exists(target_dir) and not os.listdir(target_dir):
            if os.path.exists(source_dir):
                for item in os.listdir(source_dir):
                    s = os.path.join(source_dir, item)
                    d = os.path.join(target_dir, item)
                    if os.path.isfile(s):
                        shutil.copy2(s, d)
                    elif os.path.isdir(s):
                        shutil.copytree(s, d, dirs_exist_ok=True)
