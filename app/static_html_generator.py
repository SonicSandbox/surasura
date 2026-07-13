import os
import sys
import json
import pandas as pd
import webbrowser

from app.path_utils import get_user_file, get_resource
from app import settings_manager

# Configuration
RESULTS_DIR = get_user_file("results")
PROGRESSIVE_CSV = os.path.join(RESULTS_DIR, "progressive_learning_list.csv")
PRIORITY_CSV = os.path.join(RESULTS_DIR, "priority_learning_list.csv")
OUTPUT_FILE = os.path.join(RESULTS_DIR, "reading_list_static.html")
# Resources (Templates)
WEB_APP_FILE = get_resource(os.path.join("templates", "web_app.html"))

def open_as_app(file_path):
    """
    Attempts to open the HTML file in a 'tightened' browser window (App Mode).
    Falls back to the default browser if Chrome is not found.
    """
    import subprocess
    url = f"file://{os.path.abspath(file_path)}"
    
    if sys.platform == "win32":
        # Search for Chrome which supports the --app flag
        possible_browsers = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        ]
        
        for browser_path in possible_browsers:
            if os.path.exists(browser_path):
                try:
                    # Launch in app mode
                    subprocess.Popen([browser_path, f"--app={url}"])
                    return
                except Exception as e:
                    print(f"Warning: Failed to launch {browser_path} in app mode: {e}")
    
    # Fallback to standard browser behavior
    webbrowser.open(url)


def open_report(app_mode=False):
    """Open the ALREADY-generated report without re-rendering it — the fast path when neither the
    analysis nor the presentation (theme / Zen limit / window) changed. Returns False if there is
    no report on disk yet (caller should render instead)."""
    if not os.path.exists(OUTPUT_FILE):
        return False
    if app_mode:
        open_as_app(OUTPUT_FILE)
    else:
        webbrowser.open(f"file://{os.path.abspath(OUTPUT_FILE)}")
    return True


def compress_list_of_dicts(data_list):
    """
    Compresses a list of dictionaries into a compact format:
    {"keys": ["key1", "key2", ...], "rows": [["val1", "val2", ...], ...]}
    Reduces JSON payload size by removing repetitive keys.
    """
    if not data_list:
        return {"keys": [], "rows": []}
    
    # Extract superset of all keys in case some dicts are missing keys
    keys_set = set()
    for item in data_list:
        keys_set.update(item.keys())
    
    keys = list(keys_set)
    # Important: sort keys to ensure consistent ordering though not strictly required
    keys.sort() 
    
    rows = []
    for item in data_list:
        row = []
        for key in keys:
            row.append(item.get(key, None))
        rows.append(row)
        
    return {"keys": keys, "rows": rows}

def generate_static_html(theme="default", app_mode=False, zen_limit=0):
    print(f"Generating static HTML (Theme: {theme})...")
    
    # Pre-load settings
    try:
        settings = settings_manager.load_settings()
        target_lang = settings.get("target_language", "ja")
    except Exception:
        settings = {}
        target_lang = "ja"
    data = {
        "progressive": [],
        "priority": []
    }

    # Load File Statistics
    STATS_JSON = os.path.join(RESULTS_DIR, "file_statistics.json")
    stats_map = {}
    if os.path.exists(STATS_JSON):
        try:
            with open(STATS_JSON, 'r', encoding='utf-8') as f:
                stats = json.load(f)
                for s in stats:
                    stats_map[s["File"]] = s
        except Exception as e:
            print(f"Error loading stats JSON: {e}")

    # Track overall order from statistics
    all_files_order = []
    if os.path.exists(STATS_JSON):
        try:
            with open(STATS_JSON, 'r', encoding='utf-8') as f:
                stats = json.load(f)
                all_files_order = [s["File"] for s in stats]
        except: pass

    # Load Progressive
    if os.path.exists(PROGRESSIVE_CSV):
        try:
            df = pd.read_csv(PROGRESSIVE_CSV)
            # Group by Source File
            files_order = df.groupby("Source File")["Sequence"].min().sort_values().index.tolist()
            
                
            grouped = df.groupby("Source File")
            for filename in files_order:
                group = grouped.get_group(filename)
                words = group.to_dict(orient="records")
                compressed_words = compress_list_of_dicts(words)
                
                # Get total words from stats if available
                total_words = stats_map.get(filename, {}).get("Total Words", 0)
                
                # Determine if Goal Content
                is_goal_content = False
                try:
                    from app.path_utils import get_user_files_path
                    # GoalContent is in User Files/<lang>/GoalContent
                    goal_dir = os.path.join(get_user_files_path(target_lang), "GoalContent")
                    
                    # Check if file exists in GoalContent
                    if os.path.exists(os.path.join(goal_dir, filename)):
                        is_goal_content = True
                except Exception:
                    pass

                data["progressive"].append({
                    "filename": filename,
                    "words": compressed_words,
                    "total_words": total_words,
                    "is_goal_content": is_goal_content
                })
        except Exception as e:
            print(f"Error loading progressive CSV: {e}")

    data["completed_files"] = []
    
    # specific progressive files
    prog_filenames = {item["filename"] for item in data["progressive"]}
    
    # Find files in stats but not in progressive
    for fname, fstat in stats_map.items():
        if fname not in prog_filenames:
            data["completed_files"].append({
                "filename": fname,
                "stats": fstat
            })

    # Load Priority
    if os.path.exists(PRIORITY_CSV):
        try:
            df = pd.read_csv(PRIORITY_CSV)
            raw_priority = df.to_dict(orient="records")
            data["priority"] = compress_list_of_dicts(raw_priority)
        except Exception as e:
            print(f"Error loading priority CSV: {e}")

    data["file_order"] = all_files_order

    # Zen Mode Limit (Slicing)
    if "zen" in theme.lower() and zen_limit > 0:
        print(f"Applying Zen Mode Limit: {zen_limit} words")
        count = 0
        new_progressive = []
        for item in data["progressive"]:
            if count >= zen_limit:
                break
            
            if 'rows' in item["words"]:
                # Compressed dictionary
                words = item["words"]["rows"]
            else:
                words = item["words"]
                
            needed = zen_limit - count
            
            if len(words) > needed:
                if 'rows' in item["words"]:
                    item["words"]["rows"] = words[:needed]
                else:
                    item["words"] = words[:needed]
                new_progressive.append(item)
                count += needed
                break
            else:
                new_progressive.append(item)
                count += len(words)
        
        data["progressive"] = new_progressive

    # 2. Read Template
    # Accept the display name ("Zen Mode", from View Vocab Journey) and the theme id
    # ("zen-focus", forwarded by the analyzer on Generate Journey) so both paths pick Zen.
    if theme in ("Zen Mode", "zen-focus"):
        WEB_APP_FILE = get_resource(os.path.join("templates", "zen_app.html"))
    else:
        WEB_APP_FILE = get_resource(os.path.join("templates", "web_app.html"))

    if not os.path.exists(WEB_APP_FILE):
        print(f"Error: Template file {WEB_APP_FILE} not found.")
        return

    with open(WEB_APP_FILE, "r", encoding="utf-8") as f:
        html_content = f.read()

    # 3. Inject Data, Theme, and Favicon
    import base64
    from app.path_utils import get_icon_path
    
    # Load Logic Settings for injection
    logic_settings = {}
    target_lang = "ja" # Default
    theme_map = {
        'Default (Dark)': 'default',
        'Dark Flow': 'world-class',
        'Midnight (Vibrant)': 'midnight-vibrant',
        'Modern Light': 'modern-light',
        'Zen Mode': 'zen-focus',
        'default': 'default',
        'world-class': 'world-class',
        'midnight-vibrant': 'midnight-vibrant',
        'modern-light': 'modern-light'
    }
    applied_theme = theme_map.get(theme, theme)

    try:
        settings = settings_manager.load_settings()
        logic_settings = settings.get("logic", {})
        target_lang = settings.get("target_language", "ja")
        
        # If theme is 'default', try to load from settings and MAP it
        if applied_theme == "default":
            raw_theme = settings.get("theme", "default")
            applied_theme = theme_map.get(raw_theme, 'default')
    except Exception as e:
        print(f"Warning: Could not load logic settings for HTML injection: {e}")

    # Escape "</" so a literal "</script>" in user content (filenames / context sentences)
    # cannot close the inline <script> block early and blank the whole report.
    json_str = json.dumps(data).replace("</", "<\\/")
    logic_json_str = json.dumps(logic_settings).replace("</", "<\\/")
    words_per_day = settings.get("words_per_day", 5) if 'settings' in locals() else 5
    show_words_per_day = settings.get("show_words_per_day", True) if 'settings' in locals() else True

    html_content = html_content.replace(
        "let globalData = null;", 
        f"let globalData = {json_str};\n        let globalTheme = '{applied_theme}';\n        let globalLogic = {logic_json_str};\n        let globalLanguage = '{target_lang}';\n        let globalWordsPerDay = {words_per_day};\n        let globalShowWordsPerDay = {'true' if show_words_per_day else 'false'};"
    )

    # Embed Icon as Favicon and Header Logo
    icon_path = get_icon_path()
    if os.path.exists(icon_path):
        try:
            with open(icon_path, "rb") as icon_file:
                encoded_string = base64.b64encode(icon_file.read()).decode()
                
                # Injects favicon
                favicon_tag = f'<link rel="icon" type="image/png" href="data:image/png;base64,{encoded_string}">'
                html_content = html_content.replace("<head>", f"<head>\n    {favicon_tag}")
                
                # Injects logo into header
                logo_html = f'<img src="data:image/png;base64,{encoded_string}" alt="Logo" class="header-logo" style="height: 32px; width: 32px; margin-right: 15px; border-radius: 4px;">'
                html_content = html_content.replace("<h1>Surasura List</h1>", 
                                                 f'<div style="display:flex; align-items:center;">{logo_html}<h1>Surasura List</h1></div>')
        except Exception as e:
            print(f"Warning: Could not embed icon in HTML: {e}")

    # 4. Write Output
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"Static HTML generated at: {OUTPUT_FILE}")
    if app_mode:
        open_as_app(OUTPUT_FILE)
    else:
        url = f"file://{os.path.abspath(OUTPUT_FILE)}"
        webbrowser.open(url)

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--theme", default="default", help="Theme name")
    parser.add_argument("--app-mode", action="store_true", help="Launch in professional app mode")
    parser.add_argument("--zen-limit", type=int, default=0, help="Limit words for Zen Mode")
    args = parser.parse_args()
    generate_static_html(theme=args.theme, app_mode=args.app_mode, zen_limit=args.zen_limit)

if __name__ == "__main__":
    main()
