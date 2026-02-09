import urllib.request
import urllib.error
import json
import logging
from typing import Optional, Tuple

# Simple logger setup
logger = logging.getLogger(__name__)


import re

def parse_version(version_str: str) -> Tuple[int, ...]:
    """
    Robust semantic version parser.
    Extracts the first occurrence of X.Y.Z (or X.Y) from string.
    e.g., 'v1.0.0' -> (1, 0, 0)
          'Beta-Production-1.1' -> (1, 1)
    """
    try:
        # Search for version pattern: digits.digits(.digits)*
        match = re.search(r'(\d+(?:\.\d+)+)', version_str)
        if match:
            v_str = match.group(1)
            return tuple(map(int, v_str.split('.')))
    except Exception:
        pass
        
    return (0, 0, 0)



def check_for_updates(current_version: str, repo: str = "SonicSandbox/surasura") -> Optional[Tuple[str, str]]:
    """
    Checks GitHub for a newer release.
    Returns (new_version_tag, html_url) if an update is found, else None.
    Handles no-release and network errors gracefully.
    """
    api_url = f"https://api.github.com/repos/{repo}/releases/latest"
    
    try:
        # GitHub API requires a User-Agent
        req = urllib.request.Request(
            api_url, 
            headers={'User-Agent': 'Surasura-Readability-Analyzer'}
        )
        
        # Set a timeout to avoid hanging the background thread indefinitely
        with urllib.request.urlopen(req, timeout=10) as response:
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

