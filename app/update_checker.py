import urllib.request
import urllib.error
import json
import logging
from typing import Optional, Tuple

# Simple logger setup
logger = logging.getLogger(__name__)

def parse_version(version_str: str) -> Tuple[int, ...]:
    """Basic semantic version parser (e.g., 'v1.0.0' -> (1, 0, 0))"""
    clean_v = version_str.lower().strip().lstrip('v')
    try:
        return tuple(map(int, clean_v.split('.')))
    except (ValueError, AttributeError):
        return (0, 0, 0)

def check_for_updates(current_version: str, repo: str = "SonicSandbox/surasura") -> Optional[Tuple[str, str]]:
    """
    Checks GitHub for a newer release.
    Returns (new_version_tag, html_url) if an update is found, else None.
    Handles no-release and network errors gracefully.
    """
    api_url = f"https://api.github.com/repos/{repo}/releases/latest"
    
    try:
        # Set a timeout to avoid hanging the background thread indefinitely
        with urllib.request.urlopen(api_url, timeout=10) as response:
            if response.getcode() == 200:
                data = json.loads(response.read().decode())
                latest_tag = data.get("tag_name")
                html_url = data.get("html_url")
                
                if not latest_tag or not html_url:
                    return None
                
                # Compare versions
                current_v_tuple = parse_version(current_version)
                latest_v_tuple = parse_version(latest_tag)
                
                if latest_v_tuple > current_v_tuple:
                    return latest_tag, html_url
            
    except urllib.error.HTTPError as e:
        # 404 means no releases found yet, which is expected based on user comment
        if e.code != 404:
            logger.error(f"HTTP Error checking for updates: {e}")
    except Exception as e:
        logger.error(f"Unexpected error checking for updates: {e}")
        
    return None
