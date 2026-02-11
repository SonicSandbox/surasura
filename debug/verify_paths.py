import os
import sys
import shutil

# Ensure package root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.path_utils import get_user_file, get_data_path, get_user_files_path, ensure_data_setup

def verify_language(lang):
    print(f"\n--- Verifying Language: {lang} ---")
    
    # 1. Check Paths
    data_path = get_data_path(lang)
    user_files_path = get_user_files_path(lang)
    print(f"Data Path: {data_path}")
    print(f"User Files Path: {user_files_path}")
    
    # 2. Run Setup
    ensure_data_setup(lang)
    
    # 3. Verify Folders Exist
    if os.path.exists(data_path):
        print(f"[PASS] Data folder exists: {data_path}")
    else:
        print(f"[FAIL] Data folder missing: {data_path}")
        
    if os.path.exists(user_files_path):
        print(f"[PASS] User Files folder exists: {user_files_path}")
    else:
        print(f"[FAIL] User Files folder missing: {user_files_path}")
        
    # 4. Verify Subfolders in Data
    for sub in ["HighPriority", "LowPriority", "GoalContent", "Processed"]:
        sub_path = os.path.join(data_path, sub)
        if os.path.exists(sub_path):
            print(f"[PASS] Subfolder exists: {sub}")
        else:
            print(f"[FAIL] Subfolder missing: {sub}")

    # 5. Verify Lists in User Files
    for list_file in ["IgnoreList.txt", "Blacklist.txt", "KnownWord.json"]:
        # KnownWord might not exist yet if not created, but Ignore/Blacklist should be created by ensure_data_setup
        file_path = os.path.join(user_files_path, list_file)
        if list_file == "KnownWord.json":
             # We don't auto-create KnownWord.json in ensure_data_setup, so skip checking it for existence unless we know it should be there.
             pass
        else:
            if os.path.exists(file_path):
                print(f"[PASS] {list_file} exists.")
            else:
                print(f"[FAIL] {list_file} missing.")

def main():
    print("Starting Path Verification...")
    
    # Verify JA
    verify_language('ja')
    
    # Verify ZH
    verify_language('zh')
    
    # Verify Legacy/None (should default to base but we are moving away from it?)
    # get_data_path(None) -> data
    # We want to check if that still works or if we are strict.
    print(f"\n--- Verifying None (Legacy Base) ---")
    print(f"Base Data: {get_data_path(None)}")
    print(f"Base User Files: {get_user_files_path(None)}")

if __name__ == "__main__":
    main()
