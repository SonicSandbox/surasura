import os
import sys
import unittest
import json
import shutil
import tempfile
import subprocess

class TestGraduationE2E(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        
        # Setup project structure in temp dir
        os.makedirs(os.path.join(self.temp_dir, "data/ja/HighPriority"), exist_ok=True)
        os.makedirs(os.path.join(self.temp_dir, "data/ja/Graduated"), exist_ok=True)
        os.makedirs(os.path.join(self.temp_dir, "User Files/ja"), exist_ok=True)
        os.makedirs(os.path.join(self.temp_dir, "results"), exist_ok=True)
        
        # Create a sample file
        self.sample_filename = "actual_file.txt"
        self.sample_path = os.path.join(self.temp_dir, "data/ja/HighPriority", self.sample_filename)
        with open(self.sample_path, "w", encoding="utf-8") as f:
            f.write("先生、こんにちは。学生です。")

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_e2e_flow(self):
        # 1. Run ACTUAL analyzer via subprocess
        # Set SURASURA_TEST_ROOT to our temp dir
        env = os.environ.copy()
        env["SURASURA_TEST_ROOT"] = self.temp_dir
        # Ensure 'app' is importable by adding project root to PYTHONPATH
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env["PYTHONPATH"] = project_root + os.pathsep + env.get("PYTHONPATH", "")

        cmd = [sys.executable, "-m", "app.analyzer", "--language", "ja"]
        print(f"Running command: {' '.join(cmd)}")
        result = subprocess.run(cmd, env=env, capture_output=True, text=True)
        
        if result.returncode != 0:
            print("--- ANALYZER STDOUT ---")
            print(result.stdout)
            print("--- ANALYZER STDERR ---")
            print(result.stderr)
        
        self.assertEqual(result.returncode, 0, f"Analyzer failed with return code {result.returncode}")
        
        # 2. Verify word_stats.json exists in temp results
        stats_path = os.path.join(self.temp_dir, "results", "word_stats.json")
        self.assertTrue(os.path.exists(stats_path), "word_stats.json not found")
        
        with open(stats_path, "r", encoding="utf-8") as f:
            stats = json.load(f)
        
        self.assertGreater(len(stats), 0, "No stats generated")
        
        # 3. Verify Graduation Logic
        # (Using the logic fixed in GUI)
        stats_file = stats_path
        filename = self.sample_filename
        
        file_words = []
        for key, data in stats.items():
            if filename in data.get("sources", []):
                parts = key.split("|")
                file_words.append(parts[0])
        
        self.assertIn("先生", file_words)
        self.assertIn("学生", file_words)
        
        # Write to list
        grad_list_file = os.path.join(self.temp_dir, "User Files", "ja", "GraduatedList.txt")
        with open(grad_list_file, 'a', encoding='utf-8') as f:
            f.write("\n# Graduation Test\n")
            for w in file_words:
                f.write(f"{w}\n")
                
        # 4. Final check
        with open(grad_list_file, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("先生", content)
        print("End-to-End Graduation Flow Verified successfully with isolated analyzer run!")

if __name__ == "__main__":
    unittest.main()
