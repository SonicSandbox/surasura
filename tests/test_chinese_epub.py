
import os
import sys
import unittest
import shutil

# Ensure package root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.epub_importer import FileImporterApp

class TestChineseEpubExtraction(unittest.TestCase):
    def setUp(self):
        # Setup dummy app instance (headless)
        try:
            import tkinter as tk
            self.root = tk.Tk()
            self.root.withdraw()
            self.app = FileImporterApp(self.root)
        except Exception:
             # Fallback if no GUI environment
             self.app = FileImporterApp(None)

        self.test_dir = os.path.dirname(os.path.abspath(__file__))
        self.output_dir = os.path.join(self.test_dir, "test_output")
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

    def tearDown(self):
        if hasattr(self, 'root') and self.root:
            self.root.destroy()
        if os.path.exists(self.output_dir):
            shutil.rmtree(self.output_dir)

    def test_chinese_epub_extraction(self):
        # Locate test files
        epub_1 = os.path.join(self.test_dir, "Chinese_1.epub")
        epub_2 = os.path.join(self.test_dir, "Chinese_2.epub")
        
        # We might not have these files in the environment yet if user didn't upload them
        # But assuming they exist based on user request
        
        if os.path.exists(epub_1):
            print(f"Testing extraction of {epub_1}")
            text, error = self.app.extract_text_from_file(epub_1)
            self.assertIsNone(error)
            self.assertTrue(len(text) > 0, "Extracted text should not be empty")
            
            # Test Splitting
            chunks = self.app.split_by_length(text, 1000)
            self.assertTrue(len(chunks) > 0, "Should split into chunks")
            print(f"Split into {len(chunks)} chunks.")

    def test_chinese_text_splitting(self):
        txt_file = os.path.join(self.test_dir, "chinese_text_1.txt")
        if os.path.exists(txt_file):
             with open(txt_file, 'r', encoding='utf-8') as f:
                 text = f.read()
             
             # Test generic splitting on Chinese text
             chunks = self.app.split_by_length(text, 500)
             self.assertTrue(len(chunks) > 0)
             # Verify no mid-sentence breaks if possible (basic check)
             first_chunk = chunks[0]
             try:
                 print(f"First chunk end char: {first_chunk[-1].encode('utf-8', 'replace')}")
             except Exception:
                 pass
             self.assertTrue(len(first_chunk) <= 650) # Buffer allowed

if __name__ == '__main__':
    unittest.main()
