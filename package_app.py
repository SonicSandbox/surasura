import os
import shutil
import subprocess
import sys
import argparse
import json

def get_version():
    """Reads the version from app/__init__.py without importing the package."""
    init_path = os.path.join("app", "__init__.py")
    with open(init_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.startswith('__version__'):
                delim = '"' if '"' in line else "'"
                return line.split(delim)[1]
    return "0.0"

def build(zip_output=False):
    version = get_version()
    build_name = f"Surasura_v{version}"
    print(f"Building Readability Analyzer {build_name}...")
    
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
        os.path.join("packaging", "Surasura.spec")
    ]
    
    print(f"Running: {' '.join(cmd)}")
    
    # Ensure debug folder exists for logs
    if not os.path.exists("debug"):
        os.makedirs("debug", exist_ok=True)
        
    with open(os.path.join("debug", "build_log.txt"), "w") as log_file:
        result = subprocess.run(cmd, stdout=log_file, stderr=subprocess.STDOUT)
    
    if result.returncode != 0:
        print("Build failed. Check debug/build_log.txt for details.")
        return

    # Post-Build: Create Distribution Folder
    print("Creating Distribution Package...")
    final_dist = os.path.join("dist", build_name)
    
    # Clean previous distribution logic removed because we already cleaned dist at the start
    # and PyInstaller works directly in this folder now.


    # 1. Handle Built Files
    # The spec file is configured to output directly to dist/{build_name}
    # So we just need to verify it exists.
    
    if not os.path.exists(final_dist):
        print(f"Error: Build output not found at {final_dist}")
        return

    print(f"Build output verified at {final_dist}")

    # 2. Copy User Files (SANITIZED)
    print("Copying User Files (Sanitized)...")
    dst_user_files_base = os.path.join(final_dist, "User Files")
    os.makedirs(dst_user_files_base, exist_ok=True)
    
    supported_languages = ["ja", "zh"]
    
    # A. Global Files (None Currently)

    # B. Language Specific User Files
    for lang in supported_languages:
        dst_user_files_lang = os.path.join(dst_user_files_base, lang)
        os.makedirs(dst_user_files_lang, exist_ok=True)
        
        # NOTE: KnownWord.json is explicitly EXCLUDED from build.
        # Users start with a clean slate.

        # Create/Copy Ignore List
        src_ignore = os.path.join("User Files", lang, "IgnoreList.txt")
        if os.path.exists(src_ignore):
             shutil.copy2(src_ignore, os.path.join(dst_user_files_lang, "IgnoreList.txt"))
        else:
            with open(os.path.join(dst_user_files_lang, "IgnoreList.txt"), "w", encoding="utf-8") as f:
                f.write("# Add words to ignore here (one per line)\n")

        # Copy Blacklist
        src_blacklist = os.path.join("User Files", lang, "Blacklist.txt")
        if os.path.exists(src_blacklist):
            print(f"Bundling Blacklist for {lang}...")
            shutil.copy2(src_blacklist, os.path.join(dst_user_files_lang, "Blacklist.txt"))
        
        # Copy Specific Frequency List (Only for JA)
        if lang == "ja":
            specific_freq_list = "frequency_list_ja_global50k.csv"
            src_freq = os.path.join("User Files", "ja", specific_freq_list)
            if os.path.exists(src_freq):
                print(f"Bundling specific frequency list: {specific_freq_list}")
                shutil.copy2(src_freq, os.path.join(dst_user_files_lang, specific_freq_list))
        
    # C. Copy Global Frequency Lists (CSV)
    # Removed: We only bundle the specific 'frequency_list_ja_global50k.csv' now.


    # D. Copy Legacy Yomitan Frequency Lists (Zips) - Optional/Legacy
    freq_lists_legacy = [
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
    for freq_file in freq_lists_legacy:
        src_freq = os.path.join("User Files", freq_file)
        if os.path.exists(src_freq):
            shutil.copy2(src_freq, os.path.join(dst_user_files_base, freq_file))

    # 3. Create Data Directories and Copy Samples
    print("Creating Data Directories and Copying Samples...")
    data_dir_base = os.path.join(final_dist, "data")
    
    for lang in supported_languages:
        data_dir_lang = os.path.join(data_dir_base, lang)
        os.makedirs(data_dir_lang, exist_ok=True)
        
        for category in ["HighPriority", "LowPriority", "GoalContent", "Processed"]:
            cat_dir = os.path.join(data_dir_lang, category)
            os.makedirs(cat_dir, exist_ok=True)
            
            # Copy samples from samples/<lang>/<category>
            sample_src = os.path.join("samples", lang, category)
            if os.path.exists(sample_src):
                print(f"Bundling samples for {lang}/{category}...")
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
        (os.path.join("docs", "releases", f"RELEASE_v{version}.md"), f"RELEASE_v{version}.md")
    ]

    for src, dst_name in docs_to_copy:
        if os.path.exists(src):
             shutil.copy2(src, os.path.join(final_dist, dst_name))
        else:
            print(f"Warning: Documentation file not found: {src}")

    # 6. Generate Clean Settings for Distribution
    print("Generating Clean Settings for Distribution...")
    try:
        from app import settings_manager
        # Get defaults
        clean_settings = settings_manager.get_default_settings()
        # Ensure 'hide_satoru' is GONE
        if "hide_satoru" in clean_settings:
            del clean_settings["hide_satoru"]
            
        settings_dst = os.path.join(final_dist, "settings.json")
        with open(settings_dst, 'w', encoding='utf-8') as f:
            json.dump(clean_settings, f, indent=4)
        print(f"Clean settings.json created at {settings_dst}")
    except Exception as e:
        print(f"Warning: Could not generate clean settings: {e}")

    # 7. Create Zip Archive
    if zip_output:
        print("Creating Zip Archive...")
        archive_base = os.path.join("dist", build_name) # Will create {build_name}.zip in dist/
        try:
            shutil.make_archive(archive_base, 'zip', final_dist)
            print(f"Zip archive created: {archive_base}.zip")
        except Exception as e:
            print(f"Warning: Could not create zip archive: {e}")
    else:
        print("Skipping Zip Archive creation (use --zip to enable).")

    print("\n---------------------------------------------------")
    print(f"Build Complete! Package located at: {os.path.abspath(final_dist)}")
    if zip_output:
        print(f"Zip Archive: {os.path.abspath(archive_base + '.zip')}")
    print("---------------------------------------------------")

    # Open the dist folder in File Explorer
    try:
        os.startfile(os.path.abspath("dist"))
    except Exception:
        pass

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build and package Surasura.")
    parser.add_argument("--zip", action="store_true", help="Create a zip archive of the distribution folder.")
    args = parser.parse_known_args()[0]
    build(zip_output=args.zip)
