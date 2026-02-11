import os
import re

HTML_FILE = r"C:\Users\Michael\WorldDomination\Surasura - Readability Analyzer\surasura\results\reading_list_static.html"

if not os.path.exists(HTML_FILE):
    print("Error: HTML file not found.")
    exit(1)

with open(HTML_FILE, "r", encoding="utf-8") as f:
    content = f.read()

# Check for CSS fix
if ".progressive-container {" in content and "max-width: 800px;" in content:
    print("[PASS] CSS for centering found.")
else:
    print("[FAIL] CSS for centering NOT found.")

# Check for wordsContainer creation
if "const wordsContainer = document.createElement('div');" in content:
    print("[PASS] wordsContainer creation found.")
else:
    print("[FAIL] wordsContainer creation NOT found.")

# Check for try-catch around setupInfiniteScroll
if "try {" in content and "setupInfiniteScroll(wordsContainer" in content:
    print("[PASS] try-catch around setupInfiniteScroll found.")
else:
    print("[FAIL] try-catch around setupInfiniteScroll NOT found.")

# Check for removal of contain: content
if "fileSection.style.contain = \"content\";" not in content:
    print("[PASS] 'contain: content' optimization removed.")
else:
    print("[FAIL] 'contain: content' STILL PRESENT.")
