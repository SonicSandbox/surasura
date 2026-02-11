import unittest
import json
import os
import shutil
import tempfile

class TestGraduateLogic(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.stats_path = os.path.join(self.test_dir, "word_stats.json")
        self.grad_list_path = os.path.join(self.test_dir, "GraduatedList.txt")
        
        # Create dummy word_stats.json
        # Format: "lemma|reading": {"sources": ["file1.txt", "file2.txt"], ...}
        self.dummy_stats = {
            "cat|neko": {"sources": ["novel.txt", "anime.srt"], "score": 10},
            "dog|inu": {"sources": ["novel.txt"], "score": 10},
            "bird|tori": {"sources": ["anime.srt"], "score": 5}
        }
        with open(self.stats_path, "w", encoding="utf-8") as f:
            json.dump(self.dummy_stats, f)
            
        # Create empty GraduatedList.txt
        with open(self.grad_list_path, "w", encoding="utf-8") as f:
            f.write("# Header\n")

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def graduate_file_logic(self, target_filename):
        """
        The logic to be implemented in the GUI.
        Reads stats, finds words from target_filename, appends to list.
        """
        if not os.path.exists(self.stats_path):
            return 0
            
        with open(self.stats_path, 'r', encoding='utf-8') as f:
            stats = json.load(f)
            
        words_to_graduate = []
        for key, data in stats.items():
            if target_filename in data.get("sources", []):
                # key is "lemma|reading"
                parts = key.split("|")
                lemma = parts[0]
                words_to_graduate.append(lemma)
        
        if not words_to_graduate:
            return 0
            
        # Sort for consistency
        words_to_graduate.sort()
        
        with open(self.grad_list_path, 'a', encoding='utf-8') as f:
            f.write(f"\n# Source: {target_filename}\n")
            for word in words_to_graduate:
                f.write(f"{word}\n")
                
        return len(words_to_graduate)

    def test_graduate_novel(self):
        count = self.graduate_file_logic("novel.txt")
        
        # Should match "cat" and "dog"
        self.assertEqual(count, 2)
        
        with open(self.grad_list_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        self.assertIn("# Source: novel.txt", content)
        self.assertIn("cat", content)
        self.assertIn("dog", content)
        self.assertNotIn("bird", content)

    def test_graduate_anime(self):
        count = self.graduate_file_logic("anime.srt")
        
        # Should match "cat" and "bird"
        self.assertEqual(count, 2)
        
        with open(self.grad_list_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        self.assertIn("# Source: anime.srt", content)
        self.assertIn("cat", content)
        self.assertIn("bird", content)
        self.assertNotIn("dog", content)

if __name__ == "__main__":
    unittest.main()
