
import sys
import subprocess
import os

def main():
    """
    Run the comprehensive test suite for Surasura.
    """
    # 1. Setup environment
    project_root = os.path.dirname(os.path.abspath(__file__))
    test_dir = os.path.join(project_root, "tests")
    
    print("\n" + "="*60)
    print("   SURASURA TEST SUITE RUNNER")
    print("="*60 + "\n")
    
    # 2. Command Construction: Use pytest
    # -v: Verbose output
    # -ra: Show extra test summary info
    cmd = [sys.executable, "-m", "pytest", test_dir, "-v", "-ra"]
    
    try:
        # 3. Execution
        result = subprocess.run(cmd, env=os.environ.copy())
        
        # 4. Result Handling
        print("\n" + "-"*60)
        if result.returncode == 0:
            print("  [PASS]  ALL TESTS PASSED")
        else:
            print("  [FAIL]  TESTS FAILED")
        print("-" * 60)
        
        sys.exit(result.returncode)
        
    except FileNotFoundError:
        print("Error: Pytest not found. Please install dependencies: pip install requirements.txt")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nTest run cancelled via KeyboardInterrupt.")
        sys.exit(130)

if __name__ == "__main__":
    main()
