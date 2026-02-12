
import os

file_path = r"c:\Users\Michael\WorldDomination\Surasura - Readability Analyzer\surasura\results\reading_list_static.html"

if not os.path.exists(file_path):
    print("File not found")
    exit(1)

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

if "migaku_ignore" in content:
    print("SUCCESS: migaku_ignore found")
else:
    print("FAILURE: migaku_ignore NOT found")

if "createWordItem" in content:
     print("SUCCESS: createWordItem found")
else:
     print("FAILURE: createWordItem NOT found")
