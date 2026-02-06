import os
import sys

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
