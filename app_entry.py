import sys
import os
import traceback
import logging

# Ensure the application is importable
app_root = os.path.dirname(os.path.abspath(__file__))
if app_root not in sys.path:
    sys.path.insert(0, app_root)

def log_error(msg):
    with open("app_debug_log.txt", "a", encoding="utf-8") as f:
        f.write(f"{msg}\n")

# Windows Taskbar Icon Fix (Set AppUserModelID)
if sys.platform == "win32":
    try:
        import ctypes
        from app import __version__
        myappid = f'SonicSandbox.Surasura.ReadabilityAnalyzer.{__version__}'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception:
        pass

import multiprocessing

def main():
    multiprocessing.freeze_support()
    try:
        log_error(f"App starting. Args: {sys.argv}")
        
        # Ensure the bundle root is in sys.path
        if getattr(sys, 'frozen', False):
            bundle_dir = sys._MEIPASS
            if bundle_dir not in sys.path:
                sys.path.insert(0, bundle_dir)
            log_error(f"Frozen mode. Bundle dir: {bundle_dir}")
        else:
            log_error("Source mode.")

        if len(sys.argv) > 1:
            command = sys.argv[1]
            log_error(f"Dispatching command: {command}")
            
            # Dispatch Logic
            if command == 'analyzer':
                from app import analyzer
                sys.argv = [sys.argv[0]] + sys.argv[2:]
                analyzer.main()
                return

            elif command == 'epub_importer':
                from app import epub_importer
                sys.argv = [sys.argv[0]] + sys.argv[2:]
                epub_importer.main()
                return

            elif command == 'migaku_importer':
                from app import migaku_db_importer_gui
                sys.argv = [sys.argv[0]] + sys.argv[2:]
                migaku_db_importer_gui.main()
                return
                
            elif command == 'static_generator':
                from app import static_html_generator
                sys.argv = [sys.argv[0]] + sys.argv[2:]
                static_html_generator.main() 
                return 
                
            elif command == 'convert_db':
                from app import migaku_converter
                sys.argv = [sys.argv[0]] + sys.argv[2:] 
                migaku_converter.main()
                return
            else:
                log_error(f"Unknown command: {command}")

        # Default: Run Main Dashboard
        log_error("Launching Dashboard")
        from app import main as dashboard
        dashboard.main()
        
    except Exception as e:
        err_msg = f"CRITICAL ERROR:\n{traceback.format_exc()}"
        log_error(err_msg)
        # Also try to show a message box if possible
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Critical Error", err_msg)
            root.destroy()
        except:
            pass
        sys.exit(1)

if __name__ == "__main__":
    main()
