import os
import sys
import json
import shutil
import tempfile
import subprocess

temp_dir = tempfile.mkdtemp()
print(f"DEBUG: Temp Dir = {temp_dir}")
try:
    # Setup project structure in temp dir
    os.makedirs(os.path.join(temp_dir, "data/ja/HighPriority"), exist_ok=True)
    os.makedirs(os.path.join(temp_dir, "data/ja/Graduated"), exist_ok=True)
    os.makedirs(os.path.join(temp_dir, "User Files/ja"), exist_ok=True)
    os.makedirs(os.path.join(temp_dir, "results"), exist_ok=True)
    
    # Create a sample file
    sample_filename = "actual_file.txt"
    sample_path = os.path.join(temp_dir, "data/ja/HighPriority", sample_filename)
    with open(sample_path, "w", encoding="utf-8") as f:
        f.write("先生、こんにちは。学生です。")

    # Run ACTUAL analyzer via subprocess
    env = os.environ.copy()
    env["SURASURA_TEST_ROOT"] = temp_dir
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env["PYTHONPATH"] = project_root + os.pathsep + env.get("PYTHONPATH", "")

    cmd = [sys.executable, "-m", "app.analyzer", "--language", "ja"]
    print(f"Running command: {' '.join(cmd)}")
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)
    
    print("--- ANALYZER STDOUT ---")
    print(result.stdout)
    print("--- ANALYZER STDERR ---")
    print(result.stderr)
    
    if result.returncode == 0:
        print("Analyzer SUCCEEDED")
        stats_path = os.path.join(temp_dir, "results", "word_stats.json")
        if os.path.exists(stats_path):
            print(f"Found word_stats.json at {stats_path}")
            with open(stats_path, "r", encoding="utf-8") as f:
                stats = json.load(f)
                print(f"Stats keys: {list(stats.keys())[:5]}")
        else:
            print("ERROR: word_stats.json NOT FOUND in temp dir")
    else:
        print(f"Analyzer FAILED with return code {result.returncode}")

finally:
    shutil.rmtree(temp_dir)
    print("Cleaned up temp dir.")
