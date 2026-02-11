import os
import json
import shutil
import tempfile

def test_graduation_logic():
    # Setup simulated environment
    with tempfile.TemporaryDirectory() as temp_dir:
        # dataroot: temp_dir/data/ja
        data_root = os.path.join(temp_dir, "data", "ja")
        os.makedirs(data_root)
        
        # results: temp_dir/results
        results_dir = os.path.join(temp_dir, "results")
        os.makedirs(results_dir)
        
        # user_files: temp_dir/User Files/ja
        user_files_dir = os.path.join(temp_dir, "User Files", "ja")
        os.makedirs(user_files_dir)
        
        # 1. Create dummy word_stats.json in results
        stats_data = {
            "test|testreading": {
                "sources": ["test_file.txt"],
                "score": 10
            }
        }
        stats_path = os.path.join(results_dir, "word_stats.json")
        with open(stats_path, 'w', encoding='utf-8') as f:
            json.dump(stats_data, f)
            
        # 2. Simulate GUI logic for finding stats_path
        # Current GUI code: 
        # stats_path = os.path.join(os.path.dirname(self.data_root), "results", "word_stats.json")
        # self.data_root is data_root (temp_dir/data/ja)
        current_gui_stats_path = os.path.join(os.path.dirname(data_root), "results", "word_stats.json")
        
        print(f"Data Root: {data_root}")
        print(f"Results Dir: {results_dir}")
        print(f"Expected Stats Path (Actual): {stats_path}")
        print(f"GUI calculated Stats Path: {current_gui_stats_path}")
        
        if os.path.exists(current_gui_stats_path):
            print("SUCCESS: GUI can find word_stats.json (Wait, it SHOULD FAIL if my sibling theory is correct)")
        else:
            print("FAILURE: GUI CANNOT find word_stats.json with current logic.")

        # 3. Simulate correct logic
        # data_root is temp_dir/data/ja
        # os.path.dirname(data_root) is temp_dir/data
        # os.path.dirname(os.path.dirname(data_root)) is temp_dir/
        correct_stats_path = os.path.join(os.path.dirname(os.path.dirname(data_root)), "results", "word_stats.json")
        print(f"Correctly calculated Stats Path: {correct_stats_path}")
        if os.path.exists(correct_stats_path):
            print("SUCCESS: Correct logic finds word_stats.json")
        else:
            print("FAILURE: Correct logic still failed? Check structure.")

if __name__ == "__main__":
    test_graduation_logic()
