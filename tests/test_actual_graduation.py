import os
import sys
import unittest
import json
import shutil
import tempfile
from collections import defaultdict

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class TestActualGraduation(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.temp_dir)
        
        # Setup structure
        os.makedirs("data/ja/HighPriority/MyFolder")
        os.makedirs("data/ja/Graduated")
        os.makedirs("User Files/ja")
        os.makedirs("results")
        
        # 1. Create a file directly in High Priority
        self.file1 = "data/ja/HighPriority/file1.txt"
        with open(self.file1, "w", encoding="utf-8") as f:
            f.write("猫") # Cat

        # 2. Create a file inside a folder
        self.file2 = "data/ja/HighPriority/MyFolder/file2.txt"
        with open(self.file2, "w", encoding="utf-8") as f:
            f.write("犬") # Dog

        # Create empty GraduatedList
        self.grad_list_path = "User Files/ja/GraduatedList.txt"
        with open(self.grad_list_path, "w", encoding="utf-8") as f:
            f.write("# Graduated Words\n")

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.temp_dir)

    def simulate_graduation_logic(self, source_path, language="ja"):
        """Mimics the logic in content_importer_gui.py"""
        project_root = "."
        stats_file = os.path.join(project_root, "results", "word_stats.json")
        
        if not os.path.exists(stats_file):
            return 0
            
        with open(stats_file, 'r', encoding='utf-8') as f:
            stats = json.load(f)
            
        filenames_to_match = set()
        if os.path.isfile(source_path):
            filenames_to_match.add(os.path.basename(source_path))
        else:
            for root, dirs, files in os.walk(source_path):
                for f in files:
                    filenames_to_match.add(f)
        
        file_words = []
        for key, data in stats.items():
            sources = data.get("sources", [])
            if any(f in sources for f in filenames_to_match):
                parts = key.split("|")
                if len(parts) >= 1:
                    file_words.append(parts[0])
        
        if file_words:
            file_words = sorted(list(set(file_words)))
            user_files_dir = os.path.join(project_root, "User Files", language)
            grad_list_file = os.path.join(user_files_dir, "GraduatedList.txt")
            
            with open(grad_list_file, 'a', encoding='utf-8') as f:
                f.write(f"\n# Source: {os.path.basename(source_path)}\n")
                for w in file_words:
                    f.write(f"{w}\n")
            return len(file_words)
        return 0

    def test_folder_graduation(self):
        # 1. Prepare word_stats.json
        # file1.txt has 猫, file2.txt has 犬
        stats = {
            "猫|neko": {"sources": ["file1.txt"]},
            "犬|inu": {"sources": ["file2.txt"]}
        }
        with open("results/word_stats.json", "w", encoding="utf-8") as f:
            json.dump(stats, f)
            
        # 2. Graduate the FOLDER "MyFolder"
        folder_path = "data/ja/HighPriority/MyFolder"
        count = self.simulate_graduation_logic(folder_path)
        
        self.assertEqual(count, 1, "Should graduate '犬' from file2.txt inside MyFolder")
        
        with open(self.grad_list_path, "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn("犬", content)
            self.assertNotIn("猫", content)

    def test_file_graduation(self):
        # 1. Prepare word_stats.json
        stats = {
            "猫|neko": {"sources": ["file1.txt"]},
            "犬|inu": {"sources": ["file2.txt"]}
        }
        with open("results/word_stats.json", "w", encoding="utf-8") as f:
            json.dump(stats, f)
            
        # 2. Graduate the FILE "file1.txt"
        count = self.simulate_graduation_logic(self.file1)
        
        self.assertEqual(count, 1, "Should graduate '猫' from file1.txt")
        
        with open(self.grad_list_path, "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn("猫", content)
            self.assertNotIn("犬", content)

    def test_no_stats_graduation(self):
        # Simulate graduating with no analysis run
        count = self.simulate_graduation_logic(self.file1)
        self.assertEqual(count, 0)
        
        with open(self.grad_list_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            # Only header should be there
            self.assertEqual(content, "# Graduated Words")

if __name__ == "__main__":
    unittest.main()
