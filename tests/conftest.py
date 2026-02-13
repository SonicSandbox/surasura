
import os
import sys
import pytest
from unittest.mock import patch

# Ensure the project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

@pytest.fixture
def test_resources_dir():
    """Returns the path to the 'tests/Test Resources' directory."""
    return os.path.join(os.path.dirname(__file__), "Test Resources")

@pytest.fixture
def ja_resources_dir(test_resources_dir):
    return os.path.join(test_resources_dir, "ja")

@pytest.fixture
def zh_resources_dir(test_resources_dir):
    return os.path.join(test_resources_dir, "zh")

@pytest.fixture(scope="session", autouse=True)
def mock_messagebox():
    """Globally mock tkinter.messagebox for all tests to prevent blocking dialogs."""
    with patch("tkinter.messagebox.showinfo"), \
         patch("tkinter.messagebox.showwarning"), \
         patch("tkinter.messagebox.showerror"), \
         patch("tkinter.messagebox.askyesno", return_value=True), \
         patch("tkinter.messagebox.askokcancel", return_value=True):
        yield

@pytest.fixture
def project_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
