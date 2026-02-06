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
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--clean",
        "--noconfirm",
        "--name", "Surasura_v1.0",
        "--onedir",
        "--windowed",
        "--add-data", "templates;templates",
        "--add-data", "scripts;scripts",
        "--collect-all", "unidic_lite",
        "--hidden-import", "pandas",
        "--hidden-import", "fugashi",
        "--hidden-import", "tkinter",
        "--hidden-import", "ebooklib",
        "--hidden-import", "bs4",
        "--exclude-module", "pandas.tests",
        "app_entry.py"
    ]
    
    print(f"Running: {' '.join(cmd)}")
    
    with open("build_log.txt", "w") as log_file:
        result = subprocess.run(cmd, stdout=log_file, stderr=subprocess.STDOUT)
    
    if result.returncode != 0:
        print("Build failed. Check build_log.txt for details.")
        return

    # Post-Build: Create Distribution Folder
    print("Creating Distribution Package...")
    final_dist = os.path.join("dist", "Surasura_Distribution_v1.0")
    
    # Clean previous distribution
    if os.path.exists(final_dist):
        print(f"Cleaning previous distribution: {final_dist}")
        try:
            shutil.rmtree(final_dist)
        except Exception as e:
            print(f"Warning: Could not clean {final_dist}: {e}")

    # 1. Handle Built Files
    src_dir = os.path.join("dist", "Surasura_v1.0")
    src_exe = os.path.join("dist", "Surasura_v1.0.exe")
    
    if os.path.exists(src_dir):
        # Onedir mode: Rename/Move the folder to the final name
        print(f"Moving {src_dir} to {final_dist}")
        shutil.move(src_dir, final_dist)
    elif os.path.exists(src_exe):
        # Onefile mode: Create folder and move exe
        os.makedirs(final_dist, exist_ok=True)
        print(f"Moving {src_exe} to {final_dist}")
        shutil.move(src_exe, os.path.join(final_dist, "Surasura_v1.0.exe"))
    else:
        print("Error: Build output not found in dist/")
        return

    # 2. Copy User Files (Config/Lists) into the package folder
    print("Copying User Files...")
    src_user_files = "User Files"
    dst_user_files = os.path.join(final_dist, "User Files")
    if os.path.exists(src_user_files):
        shutil.copytree(src_user_files, dst_user_files, dirs_exist_ok=True)
    else:
        os.makedirs(dst_user_files, exist_ok=True)

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

    print("\n---------------------------------------------------")
    print(f"Build Complete! Package located at: {os.path.abspath(final_dist)}")
    print("You can zip this folder and share it.")
    print("---------------------------------------------------")

if __name__ == "__main__":
    build()
