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

def generate_static_html(theme="default", zen_limit=50):
    print(f"Generating static HTML (Theme: {theme})...")

    # 1. Load Data
    data = {
        "progressive": [],
        "priority": []
    }

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
                data["progressive"].append({
                    "filename": filename,
                    "words": words
                })
        except Exception as e:
            print(f"Error loading progressive CSV: {e}")

    # Load Priority
    if os.path.exists(PRIORITY_CSV):
        try:
            df = pd.read_csv(PRIORITY_CSV)
            data["priority"] = df.to_dict(orient="records")
        except Exception as e:
            print(f"Error loading priority CSV: {e}")

    # 2. Read Template
    if not os.path.exists(WEB_APP_FILE):
        print(f"Error: Template file {WEB_APP_FILE} not found.")
        return

    with open(WEB_APP_FILE, "r", encoding="utf-8") as f:
        html_content = f.read()

    # 3. Inject Data and Theme
    json_str = json.dumps(data)
    html_content = html_content.replace(
        "let globalData = null;", 
        f"let globalData = {json_str};\n        let globalTheme = '{theme}';"
    )

    # 4. Write Output
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"Static HTML generated at: {OUTPUT_FILE}")
    webbrowser.open(f"file://{OUTPUT_FILE}")

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--theme", default="default", help="Theme name")
    parser.add_argument("--zen-limit", type=int, default=50, help="Word limit for Zen Focus mode")
    args = parser.parse_args()
    generate_static_html(theme=args.theme, zen_limit=args.zen_limit)

if __name__ == "__main__":
    main()
