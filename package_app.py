import os
import shutil
import subprocess
import sys

def build():
    print("Building Readability Analyzer...")
    
    # Clean previous build
    if os.path.exists("dist"):
        try:
            shutil.rmtree("dist")
        except Exception:
            pass
    if os.path.exists("build"):
        try:
            shutil.rmtree("build")
        except Exception:
            pass

    # PyInstaller Command
    # Use the spec file in packaging/ directory
    # distpath and workpath default to dist/ and build/ in the current directory
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--clean",
        "--noconfirm",
        "--distpath", "dist",
        "--workpath", "build",
        os.path.join("packaging", "Surasura_v1.1.spec")
    ]
    
    print(f"Running: {' '.join(cmd)}")
    
    with open("build_log.txt", "w") as log_file:
        result = subprocess.run(cmd, stdout=log_file, stderr=subprocess.STDOUT)
    
    if result.returncode != 0:
        print("Build failed. Check build_log.txt for details.")
        return

    # Post-Build: Create Distribution Folder
    print("Creating Distribution Package...")
    final_dist = os.path.join("dist", "Surasura_v1.1")
    
    # Clean previous distribution logic removed because we already cleaned dist at the start
    # and PyInstaller works directly in this folder now.


    # 1. Handle Built Files
    # The spec file is configured to output directly to dist/Surasura_v1.1
    # So we just need to verify it exists.
    
    if not os.path.exists(final_dist):
        print(f"Error: Build output not found at {final_dist}")
        return

    print(f"Build output verified at {final_dist}")

    # 2. Copy User Files (SANITIZED)
    print("Copying User Files (Sanitized)...")
    dst_user_files = os.path.join(final_dist, "User Files")
    os.makedirs(dst_user_files, exist_ok=True)
    
    # A. Copy Sample Known Words as the default
    src_sample_json = os.path.join("User Files", "KnownWordsSample.json")
    if os.path.exists(src_sample_json):
        shutil.copy2(src_sample_json, os.path.join(dst_user_files, "KnownWord.json"))
        # Sample file is now just KnownWord.json, no need for duplicate
    
    # B. Create Empty Ignore List
    with open(os.path.join(dst_user_files, "IgnoreList.txt"), "w", encoding="utf-8") as f:
        f.write("# Add words to ignore here (one per line)\n")
        
    # C. Copy Yomitan Frequency Lists
    freq_lists = [
        "jiten_freq_Anime.zip",
        "jiten_freq_Drama.zip",
        "jiten_freq_global.zip",
        "jiten_freq_Manga.zip",
        "jiten_freq_Movie.zip",
        "jiten_freq_NonFiction.zip",
        "jiten_freq_Novel.zip",
        "jiten_freq_VideoGame.zip",
        "jiten_freq_VisualNovel.zip",
        "jiten_freq_WebNovel.zip",
    ]
    for freq_file in freq_lists:
        src_freq = os.path.join("User Files", freq_file)
        if os.path.exists(src_freq):
            shutil.copy2(src_freq, os.path.join(dst_user_files, freq_file))

    # 3. Create Data Directories and Copy Samples
    print("Creating Data Directories and Copying Samples...")
    data_dir = os.path.join(final_dist, "data")
    os.makedirs(data_dir, exist_ok=True)
    
    for category in ["HighPriority", "LowPriority", "GoalContent", "Processed"]:
        cat_dir = os.path.join(data_dir, category)
        os.makedirs(cat_dir, exist_ok=True)
        
        # Copy samples if they exist
        sample_src = os.path.join("samples", category)
        if os.path.exists(sample_src):
            print(f"Bundling samples for {category}...")
            shutil.copytree(sample_src, cat_dir, dirs_exist_ok=True)

    # 4. Create Results Directory
    os.makedirs(os.path.join(final_dist, "results"), exist_ok=True)
    
    # 5. Copy Documentation
    # 5. Copy Documentation
    # We copy these from the docs/ folder to the root of the distribution
    # so the user sees them immediately upon opening the folder.
    
    docs_to_copy = [
        ("README.md", "README.md"),
        (os.path.join("docs", "UPDATE_INSTRUCTIONS.md"), "UPDATE_INSTRUCTIONS.md"),
        (os.path.join("docs", "releases", "RELEASE_v1.1.md"), "RELEASE_v1.1.md")
    ]

    for src, dst_name in docs_to_copy:
        if os.path.exists(src):
             shutil.copy2(src, os.path.join(final_dist, dst_name))
        else:
            print(f"Warning: Documentation file not found: {src}")

    print("\n---------------------------------------------------")
    print(f"Build Complete! Package located at: {os.path.abspath(final_dist)}")
    print("You can zip this folder and share it.")
    print("---------------------------------------------------")

if __name__ == "__main__":
    build()
