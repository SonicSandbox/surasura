
import unittest
import os
import shutil
import tempfile
import sys
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.epub_importer import FileImporterApp
import tkinter as tk

class TestEpubSplitting(unittest.TestCase):
    def setUp(self):
        # Create a dummy root for Tkinter
        self.root = tk.Tk()
        self.root.withdraw() # Hide it
        self.app = FileImporterApp(self.root)
        
        # Create a temp directory for testing output
        self.test_dir = tempfile.mkdtemp()
        self.app.processed_dir = self.test_dir

    def tearDown(self):
        self.root.destroy()
        shutil.rmtree(self.test_dir)

    def test_save_chunks_grouped_even_split(self):
        """Test splitting 10 chunks into 2 parts (5 each)"""
        chunks = [f"Chunk {i}" for i in range(10)]
        base_name = "TestBook"
        num_parts = 2
        
        msg = self.app.save_chunks_grouped(chunks, base_name, num_parts)
        
        # Check parent folder created
        parent_dir = os.path.join(self.test_dir, base_name)
        self.assertTrue(os.path.exists(parent_dir), f"Parent dir {parent_dir} should exist")
        
        # Check folders created inside parent
        part1_dir = os.path.join(parent_dir, f"{base_name}_1")
        part2_dir = os.path.join(parent_dir, f"{base_name}_2")
        
        self.assertTrue(os.path.exists(part1_dir))
        self.assertTrue(os.path.exists(part2_dir))
        
        # Check files in chunks
        self.assertEqual(len(os.listdir(part1_dir)), 5)
        self.assertEqual(len(os.listdir(part2_dir)), 5)
        
        # Verify content of first file
        with open(os.path.join(part1_dir, f"{base_name}_1_01.txt"), 'r') as f:
            self.assertEqual(f.read(), "Chunk 0")

    def test_save_chunks_grouped_uneven_split(self):
        """Test splitting 10 chunks into 3 parts (4, 4, 2)"""
        chunks = [f"Chunk {i}" for i in range(10)]
        base_name = "TestBook"
        num_parts = 3
        
        self.app.save_chunks_grouped(chunks, base_name, num_parts)
        
        parent_dir = os.path.join(self.test_dir, base_name)
        part1_dir = os.path.join(parent_dir, f"{base_name}_1")
        part2_dir = os.path.join(parent_dir, f"{base_name}_2")
        part3_dir = os.path.join(parent_dir, f"{base_name}_3")
        
        self.assertEqual(len(os.listdir(part1_dir)), 4)
        self.assertEqual(len(os.listdir(part2_dir)), 4)
        self.assertEqual(len(os.listdir(part3_dir)), 2)

    def test_save_chunks_grouped_more_parts_than_chunks(self):
        """Test asking for 5 parts when there are only 3 chunks"""
        chunks = ["C1", "C2", "C3"]
        base_name = "TestBook"
        num_parts = 5
        
        # Should cap at 3 parts, 1 file each
        self.app.save_chunks_grouped(chunks, base_name, num_parts)
        
        parent_dir = os.path.join(self.test_dir, base_name)
        self.assertTrue(os.path.exists(os.path.join(parent_dir, f"{base_name}_1")))
        self.assertTrue(os.path.exists(os.path.join(parent_dir, f"{base_name}_2")))
        self.assertTrue(os.path.exists(os.path.join(parent_dir, f"{base_name}_3")))
        self.assertFalse(os.path.exists(os.path.join(parent_dir, f"{base_name}_4")))

    def test_save_chunks_grouped_single_part(self):
        """Test handling of 1 part request (creates folder _1)"""
        chunks = ["C1", "C2"]
        base_name = "TestBook"
        num_parts = 1
        
        self.app.save_chunks_grouped(chunks, base_name, num_parts)
        
        parent_dir = os.path.join(self.test_dir, base_name)
        part1_dir = os.path.join(parent_dir, f"{base_name}_1")
        self.assertTrue(os.path.exists(part1_dir))
        self.assertEqual(len(os.listdir(part1_dir)), 2)

if __name__ == '__main__':
    unittest.main()
