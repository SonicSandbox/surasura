
import os
import sys
import subprocess

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.static_html_generator import generate_static_html

# 1. Verify Zen Mode
print("Generating Zen Mode Report...")
generate_static_html(theme="Zen Mode", zen_limit=50)
zen_file = os.path.join(os.getcwd(), "results", "reading_list_static.html")

with open(zen_file, "r", encoding="utf-8") as f:
    zen_content = f.read()

if "zen-header" in zen_content:
    print("SUCCESS: Zen Header found")
else:
    print("FAILURE: Zen Header NOT found")

if "comprehension-stats" in zen_content:
    print("SUCCESS: Comprehension Stats found in Zen Mode")
    if "Baseline (" in zen_content and "%)" in zen_content:
        print("SUCCESS: Percentages found in Legend")
    else:
        print("FAILURE: Percentages NOT found in Legend")
else:
    print("FAILURE: Comprehension Stats NOT found in Zen Mode")

if "position: sticky" in zen_content and "top: 0" in zen_content:
    print("SUCCESS: Sticky Header CSS found")
else:
    print("FAILURE: Sticky Header CSS NOT found")

if "file-section-wrapper" in zen_content:
    print("SUCCESS: Per-file wrapper found")
else:
    print("FAILURE: Per-file wrapper NOT found")

if "unicode-bidi: bidi-override" in zen_content and "direction: rtl" in zen_content:
    print("SUCCESS: Reading obfuscation CSS found")
else:
    print("FAILURE: Reading obfuscation CSS NOT found")

if 'data-reading="' in zen_content and 'class="reading' in zen_content:
    # We logic-swapped to REMOVE data-reading from the span to prevent leakage
    # But wait, did I remove it from the span tag? Yes.
    # So we should validat that reading spans do NOT have data-reading
    # Regex approach would be better but let's check for the specific pattern
    if '<span class="reading no-select" migaku_ignore data-yomichan-ignore data-reading=' in zen_content:
        print("FAILURE: data-reading attribute STILL present on reading span")
    else:
        print("SUCCESS: data-reading attribute removed from reading span")
else:
    print("SUCCESS: data-reading attribute removed (general check)")

if "background: #000;" in zen_content:
    print("SUCCESS: Header background is solid black (Session 7 verify)")

# Session 8 Checks
if 'content: attr(data-content);' in zen_content and 'unicode-bidi: bidi-override;' in zen_content:
    print("SUCCESS: Readings parsing fix (attribute-only) found")
else:
    print("FAILURE: Readings parsing fix NOT found")

if 'height: 6px;' in zen_content and 'progress-segment' in zen_content:
    print("SUCCESS: Thinner Zen Progress Bar found")
else:
    print("FAILURE: Thinner Zen Progress Bar NOT found")

if "obfReading" in zen_content:
    print("FAILURE: undefined obfReading variable found in Zen App")
else:
    print("SUCCESS: undefined obfReading variable NOT found in Zen App")

with open(r"c:\Users\Michael\WorldDomination\Surasura - Readability Analyzer\surasura\templates\web_app.html", "r", encoding="utf-8") as f:
    web_content = f.read()

if 'body.theme-world-class' in web_content and '--primary: #bb86fc !important;' in web_content:
    print("SUCCESS: Dark Flow (World Class) theme CSS found")
else:
    print("FAILURE: Dark Flow theme CSS NOT found")

# Session 9 Checks
if "replace(/\"/g, '&quot;')" in zen_content:
    print("SUCCESS: Quote escaping for readings found")
else:
    print("FAILURE: Quote escaping for readings NOT found")

if 'margin-left: 20px;' in zen_content and 'border-left: 3px solid #444;' in zen_content:
    print("SUCCESS: Enhanced Sentence Indentation found")
else:
    print("FAILURE: Enhanced Sentence Indentation NOT found")

with open(r"c:\Users\Michael\WorldDomination\Surasura - Readability Analyzer\surasura\app\main.py", "r", encoding="utf-8") as f:
    main_content = f.read()

if 'length=300' in main_content and 'textvariable=self.var_zen_limit' in main_content:
    print("SUCCESS: Extended Zen Slider with Label found")
else:
    print("FAILURE: Extended Zen Slider with Label NOT found")

import re
if re.search(r'\.zen-header\s*>\s*\*', zen_content):
    print("SUCCESS: Header child selector found")
else:
    print("FAILURE: Header child selector NOT found")

if "opacity: 0.2" in zen_content:
    print("SUCCESS: Header child opacity found")
else:
    print("FAILURE: Header child opacity NOT found")

if ".zen-header > *" in zen_content and "opacity: 0.2" in zen_content:
    print("SUCCESS: Header child opacity logic found")
else:
    pass # Already reported individual failures

if "<!-- Word List Container -->" in zen_content:
    print("SUCCESS: Clean HTML comments found")
if "< !--" in zen_content:
    print("FAILURE: Malformed HTML comments found")
else:
    print("SUCCESS: No malformed HTML comments found")

# Session 10 Checks
with open(r"c:\Users\Michael\WorldDomination\Surasura - Readability Analyzer\surasura\app\static_html_generator.py", "r", encoding="utf-8") as f:
    gen_content = f.read()

if "applied_theme = theme_map.get(raw_theme, 'default')" in gen_content:
    print("SUCCESS: Theme Mapping logic found in static_html_generator.py")
else:
    print("FAILURE: Theme Mapping logic NOT found in static_html_generator.py")

if "window.onerror = function" in zen_content:
    print("SUCCESS: Global Error Handler found in Zen App")
else:
    print("FAILURE: Global Error Handler NOT found in Zen App")

if "obfReading" in zen_content:
    print("FAILURE: undefined obfReading variable found in Zen App")
else:
    print("SUCCESS: undefined obfReading variable NOT found in Zen App")

# Session 11 Checks
if 'headerDiv.style.textAlign = "left"' in zen_content:
    print("SUCCESS: Left-aligned Header found")
else:
    print("FAILURE: Left-aligned Header NOT found")

if 'color: #fff' in zen_content and 'font-weight: bold' in zen_content and 'Target:' in zen_content and 'justify-content: space-between' in zen_content:
    print("SUCCESS: Bold White Target % in Header found")
else:
    print("FAILURE: Bold White Target % in Header NOT found")

# Session 12 Checks
if '.context-box' in zen_content and 'border-left: 3px solid #333;' in zen_content:
    print("SUCCESS: Continuous Context Border found")
else:
    print("FAILURE: Continuous Context Border NOT found")

if 'content-visibility: auto' in zen_content:
    print("SUCCESS: Performance optimization (content-visibility) found")
else:
    print("FAILURE: Performance optimization (content-visibility) NOT found")

if 'cursor: default' in zen_content and 'user-select: none' in zen_content:
    print("SUCCESS: Cursor hiding CSS found")
else:
    print("FAILURE: Cursor hiding CSS NOT found")
    
# Session 14 Checks
if 'caret-color: transparent' in zen_content:
    print("SUCCESS: Global Caret Hiding found in Zen Mode")
else:
    print("FAILURE: Global Caret Hiding NOT found in Zen Mode")

if '.context-line' in zen_content and 'user-select: text' in zen_content:
    print("SUCCESS: Context Selection Enabled found in Zen Mode")
else:
    print("FAILURE: Context Selection Enabled NOT found in Zen Mode")

# 2. Verify Dark Flow (World Class)
print("\nGenerating Dark Flow Report...")
generate_static_html(theme="world-class")
OUTPUT_HTML = os.path.join(os.getcwd(), "results", "reading_list_static.html")
with open(OUTPUT_HTML, "r", encoding="utf-8") as f:
    web_content = f.read()

if 'theme-world-class' in web_content:
    print("SUCCESS: theme-world-class class found in Dark Flow report")
else:
    print("FAILURE: theme-world-class class NOT found")

if 'caret-color: transparent' in web_content:
    print("SUCCESS: Global Caret Hiding found in Web App")
else:
    print("FAILURE: Global Caret Hiding NOT found in Web App")
    # Check if logic exists
    if "document.body.classList.add(`theme-${globalTheme}`)" in web_content:
         print("DEBUG: Logic IS present in file.")
    else:
         print("DEBUG: Logic IS NOT present in file.")
