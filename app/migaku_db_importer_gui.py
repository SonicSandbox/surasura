import tkinter as tk
import os
import sys
import glob
from datetime import datetime
import sqlite3
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import subprocess

# Ensure package root is in sys.path
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.path_utils import get_user_file, get_resource

class MigakuImporterGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Surasura - Known-Word DB Importer")
        self.root.geometry("600x500")
        self.root.resizable(True, True)
        self.root.minsize(500, 400)
        
        # Bind Escape key to close
        self.root.bind("<Escape>", lambda e: self.root.destroy())
        # Set colors and styles
        self.bg_color = "#2c3e50"
        self.text_color = "#ecf0f1"
        self.accent_color = "#3498db"
        self.root.configure(bg=self.bg_color)
        
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("TButton", padding=10, font=('Segoe UI', 10))
        
        # Use path_utils for resources
        self.script_path = Path(get_resource("scripts/extract-database-file.js"))
        self.converter_path = Path(get_resource("app/migaku_converter.py")) # It's in app/ now
        
        # Set Application Icon
        try:
            from app.path_utils import get_icon_path
            icon_path = get_icon_path()
            if os.path.exists(icon_path):
                self.icon_photo = tk.PhotoImage(file=icon_path)
                self.root.iconphoto(False, self.icon_photo)
        except Exception as e:
            print(f"Warning: Could not set icon: {e}")

        self.create_widgets()
        
    def create_widgets(self):
        # Header
        header = tk.Label(self.root, text="Known-Word DB Importer", font=('Segoe UI', 16, 'bold'), 
                         bg=self.bg_color, fg=self.text_color, pady=15)
        header.pack()
        
        # Step 1 Frame
        step1_frame = tk.LabelFrame(self.root, text="Step 1: Extract from Browser", font=('Segoe UI', 11, 'bold'),
                                  bg=self.bg_color, fg=self.accent_color, padx=20, pady=15)
        step1_frame.pack(fill="x", padx=30, pady=5)
        
        # Instructions
        step1_text = (
            "1. Open Migaku Browser\n"
            "2. Press F12 to open Console\n"
            "3. Paste code below and enter"
        )
        
        instructions1 = tk.Label(step1_frame, 
                               text=step1_text, 
                               justify="left", bg=self.bg_color, fg=self.text_color, font=('Segoe UI', 10))
        instructions1.pack(anchor="w", pady=(0, 5))
        
        # Code container
        code_frame = tk.Frame(step1_frame, bg=self.bg_color)
        code_frame.pack(fill="x", pady=5)
        
        self.code_var = tk.StringVar(value="await coreApi.Database_downloadAsFile({})")
        
        # Entry requires special variable to be set for it to be copyable if state=readonly
        # But we can just use normal state and bind Control-A
        code_entry = tk.Entry(code_frame, textvariable=self.code_var, font=('Consolas', 10), 
                            readonlybackground="#34495e", fg="#ecf0f1", bg="#34495e", relief="flat")
        # Make it read-only but selectable
        code_entry.configure(state="readonly")
        code_entry.pack(side="left", fill="x", expand=True, ipady=4)
        
        # Copy Button
        copy_btn = ttk.Button(code_frame, text="Copy", command=self.copy_script, width=8)
        copy_btn.pack(side="right", padx=(10, 0))
        
        # Step 2 Frame
        step2_frame = tk.LabelFrame(self.root, text="Step 2: Process Downloaded File", font=('Segoe UI', 11, 'bold'),
                                  bg=self.bg_color, fg=self.accent_color, padx=20, pady=15)
        step2_frame.pack(fill="x", padx=30, pady=10)
        
        instructions2 = tk.Label(step2_frame, text="Import the downloaded '.db' file.", 
                               justify="left", bg=self.bg_color, fg=self.text_color, font=('Segoe UI', 10))
        instructions2.pack(anchor="w", pady=(0, 10))
        
        # Button frame
        btn_frame = tk.Frame(step2_frame, bg=self.bg_color)
        btn_frame.pack(fill="x")
        
        # Key Buttons
        scan_btn = ttk.Button(btn_frame, text="Auto-Find in Downloads", command=self.scan_downloads)
        scan_btn.pack(side="left", padx=(0, 5), expand=True, fill="x")
        
        select_btn = ttk.Button(btn_frame, text="Select File Manually...", command=self.select_file)
        select_btn.pack(side="left", padx=(5, 0), expand=True, fill="x")
        
        # Status Log
        log_frame = tk.Frame(self.root, bg=self.bg_color)
        log_frame.pack(fill="both", expand=True, padx=30, pady=10)
        
        self.log_text = tk.Text(log_frame, height=6, font=('Consolas', 9), bg="#1a252f", fg="#bdc3c7", 
                                padx=10, pady=10, state="disabled")
        self.log_text.pack(fill="both", expand=True)
        
        self.log("Ready.")

    def log(self, message):
        self.log_text.config(state="normal")
        self.log_text.insert(tk.END, f"> {message}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state="disabled")
        self.root.update_idletasks()

    def copy_script(self):
        try:
            content = self.code_var.get()
            self.root.clipboard_clear()
            self.root.clipboard_append(content)
            self.log("Code copied to clipboard!")
            messagebox.showinfo("Success", "Code copied!\n\nPaste into the Browser Console (F12).")
        except Exception as e:
            self.log(f"Error copying script: {e}")
            messagebox.showerror("Error", f"Failed to copy script: {e}")

    def scan_downloads(self):
        self.log("Scanning Downloads folder for recent Migaku exports...")
        try:
            downloads_path = os.path.join(os.path.expanduser("~"), "Downloads")
            # Look for .db files
            list_of_files = glob.glob(os.path.join(downloads_path, '*.db'))
            
            if not list_of_files:
                self.log("No .db files found in Downloads.")
                messagebox.showinfo("Scan Result", "No .db files found in Downloads folder.")
                return

            # Sort by modification time (newest first)
            latest_files = sorted(list_of_files, key=os.path.getmtime, reverse=True)
            
            # Check top 3 files
            candidate = None
            for f in latest_files[:3]:
                if self.is_valid_migaku_db(f):
                    candidate = f
                    break
            
            if candidate:
                filename = os.path.basename(candidate)
                # Format time
                mod_time = datetime.fromtimestamp(os.path.getmtime(candidate))
                time_str = mod_time.strftime('%H:%M:%S')
                
                self.log(f"Found candidate: {filename} ({time_str})")
                
                msg = f"Found a likely Migaku export:\n\nFile: {filename}\nTime: {time_str}\n\nDo you want to import this file?"
                if messagebox.askyesno("Confirm Import", msg):
                    self.process_file_path(candidate)
            else:
                self.log("No valid Migaku export found in recent files.")
                messagebox.showwarning("Not Found", "Found .db files, but none contained the 'WordList' table expected from Migaku.")
                
        except Exception as e:
            self.log(f"Error scanning downloads: {e}")
            import traceback
            traceback.print_exc()

    def is_valid_migaku_db(self, db_path):
        try:
            # Open in read-only mode to check table
            # connect using URI
            abs_path = os.path.abspath(db_path)
            # URI encoding might be tricky on Windows, just try standard open
            conn = sqlite3.connect(f"file:{abs_path}?mode=ro", uri=True)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='WordList'")
            row = cursor.fetchone()
            conn.close()
            return row is not None
        except Exception as e:
            # Fallback
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='WordList'")
                row = cursor.fetchone()
                conn.close()
                return row is not None
            except:
                return False

    def select_file(self):
        file_path = filedialog.askopenfilename(
            title="Select Migaku Database File",
            filetypes=[("SQLite Database", "*.db"), ("All Files", "*.*")]
        )
        if file_path:
            self.process_file_path(file_path)

    def process_file_path(self, file_path):
        self.log(f"Processing: {os.path.basename(file_path)}")
        
        from app.path_utils import is_frozen
        
        try:
            # Run the converter script with UTF-8 env
            env = os.environ.copy()
            env["PYTHONUTF8"] = "1"
            
            if getattr(sys, 'frozen', False):
                # Frozen
                cmd = [sys.executable, "convert_db", file_path]
            else:
                # Source
                project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                app_entry_path = os.path.join(project_root, "app_entry.py")
                cmd = [sys.executable, app_entry_path, "convert_db", file_path]
            
            # Run subprocess
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                                     text=True, encoding='utf-8', bufsize=1, env=env)
            
            for line in process.stdout:
                line = line.strip()
                if line:
                    self.log(line)
            
            process.wait()
            
            if process.returncode == 0:
                self.log("Success! KnownWord.json updated.")
                messagebox.showinfo("Success", "Database processed successfully!\nKnownWord.json has been updated.")
            else:
                self.log("Error during processing.")
                messagebox.showerror("Error", "An error occurred while processing. Check the log.")
                
        except Exception as e:
            self.log(f"Error: {e}")
            messagebox.showerror("Error", f"Failed to run converter: {e}")

def main():
    root = tk.Tk()
    app = MigakuImporterGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
