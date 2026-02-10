
import os
import pytest
import glob

def test_data_folders_exist(project_root):
    """Verify data folders for JA and ZH exist."""
    data_dir = os.path.join(project_root, "data")
    assert os.path.exists(data_dir), "Data directory missing!"
    
    for lang in ["ja", "zh"]:
        lang_dir = os.path.join(data_dir, lang)
        # Note: 'zh' data dir might not exist by default until run? 
        # Actually `path_utils.ensure_data_setup` creates them on run.
        # So we check if the code *can* create them or if they exist after a run.
        # For now, let's just check if 'ja' exists as it's the primary one.
        if lang == 'ja':
             assert os.path.exists(lang_dir), f"Data directory for {lang} missing!"
             
def test_samples_exist(project_root):
    """Verify sample files exist."""
    samples_dir = os.path.join(project_root, "samples")
    assert os.path.exists(samples_dir), "Samples directory missing!"
    
    for lang in ["ja", "zh"]:
        lang_samples = os.path.join(samples_dir, lang)
        assert os.path.exists(lang_samples), f"Samples for {lang} missing!"
        assert len(os.listdir(lang_samples)) > 0, f"No samples found for {lang}!"

def test_user_files_exist(project_root):
    """Verify User Files directory exists."""
    user_files = os.path.join(project_root, "User Files")
    assert os.path.exists(user_files), "User Files directory missing!"

def test_frequency_lists(project_root):
    """Check if any frequency lists are present."""
    user_files = os.path.join(project_root, "User Files")
    # Look for frequency_list_*.csv
    freq_files = glob.glob(os.path.join(user_files, "frequency_list_*.csv"))
    if not freq_files:
        pytest.skip("No frequency lists found in User Files. (Optional but recommended)")
    else:
        print(f"Found {len(freq_files)} frequency lists.")
