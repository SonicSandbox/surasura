import os
import sys
import json
import pandas as pd
import webbrowser

from app.path_utils import get_user_file, get_resource

# Configuration
RESULTS_DIR = get_user_file("results")
PROGRESSIVE_CSV = os.path.join(RESULTS_DIR, "progressive_learning_list.csv")
PRIORITY_CSV = os.path.join(RESULTS_DIR, "priority_learning_list.csv")
WEB_APP_FILE = get_resource("templates/web_app.html")
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

def generate_static_html(theme="default", zen_limit=50, app_mode=False):
    print(f"Generating static HTML (Theme: {theme})...")

    # 1. Load Data
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
            
            # Zen Focus: Limit to first X words across all files
            if theme == "zen-focus":
                print(f"Zen Focus detected: Limiting to first {zen_limit} words across files.")
                df = df.head(zen_limit)
                files_order = df.groupby("Source File")["Sequence"].min().sort_values().index.tolist()
                
            grouped = df.groupby("Source File")
            for filename in files_order:
                group = grouped.get_group(filename)
                words = group.to_dict(orient="records")
                
                # Get total words from stats if available
                total_words = stats_map.get(filename, {}).get("Total Words", 0)
                
                # Determine if Goal Content
                is_goal_content = False
                try:
                    # We need to resolve the full path to check if it's in GoalContent
                    # This is heuristic since we only have basename. 
                    # We check if the file exists in the GoalContent directory.
                    from app.path_utils import get_data_path
                    goal_dir = os.path.join(get_data_path(), "GoalContent")
                    if os.path.exists(os.path.join(goal_dir, filename)):
                        is_goal_content = True
                except: pass

                data["progressive"].append({
                    "filename": filename,
                    "words": words,
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
            data["priority"] = df.to_dict(orient="records")
        except Exception as e:
            print(f"Error loading priority CSV: {e}")

    data["file_order"] = all_files_order

    # 2. Read Template
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
    try:
        settings_path = get_user_file("settings.json")
        if os.path.exists(settings_path):
            with open(settings_path, 'r', encoding='utf-8') as f:
                settings = json.load(f)
                logic_settings = settings.get("logic", {})
                target_lang = settings.get("target_language", "ja")
    except Exception as e:
        print(f"Warning: Could not load logic settings for HTML injection: {e}")

    json_str = json.dumps(data)
    logic_json_str = json.dumps(logic_settings)
    html_content = html_content.replace(
        "let globalData = null;", 
        f"let globalData = {json_str};\n        let globalTheme = '{theme}';\n        let globalLogic = {logic_json_str};\n        let globalLanguage = '{target_lang}';"
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
    parser.add_argument("--zen-limit", type=int, default=50, help="Word limit for Zen Focus mode")
    parser.add_argument("--app-mode", action="store_true", help="Launch in professional app mode")
    args = parser.parse_args()
    generate_static_html(theme=args.theme, zen_limit=args.zen_limit, app_mode=args.app_mode)

if __name__ == "__main__":
    main()
