import tkinter as tk
import os
import sys

# Ensure package root is in sys.path
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tkinter import filedialog, messagebox, ttk
import subprocess
import os
import sys
from pathlib import Path

from app.path_utils import get_user_file, get_resource

class MigakuImporterGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Surasura - Known-Word DB Importer")
        self.root.geometry("600x450")
        self.root.resizable(False, False)
        
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
        header = tk.Label(self.root, text="Known-Word DB Importer", font=('Segoe UI', 18, 'bold'), 
                         bg=self.bg_color, fg=self.text_color, pady=20)
        header.pack()
        
        # Step 1 Frame
        step1_frame = tk.LabelFrame(self.root, text="Step 1: Extract from Browser", font=('Segoe UI', 11, 'bold'),
                                  bg=self.bg_color, fg=self.accent_color, padx=20, pady=15)
        step1_frame.pack(fill="x", padx=30, pady=10)
        
        instructions1 = tk.Label(step1_frame, 
                               text="1. Open Migaku (Dictionary or Options page)\n2. Press F12 -> Console\n3. Type or paste code below and press Enter:\n   await coreApi.Database_downloadAsFile({})", 
                               justify="left", bg=self.bg_color, fg=self.text_color, font=('Segoe UI', 10))
        instructions1.pack(side="left")
        
        copy_btn = ttk.Button(step1_frame, text="Copy Script", command=self.copy_script)
        copy_btn.pack(side="right", padx=10)
        
        # Step 2 Frame
        step2_frame = tk.LabelFrame(self.root, text="Step 2: Process Downloaded File", font=('Segoe UI', 11, 'bold'),
                                  bg=self.bg_color, fg=self.accent_color, padx=20, pady=15)
        step2_frame.pack(fill="x", padx=30, pady=10)
        
        instructions2 = tk.Label(step2_frame, text="Select the '.db' file that was downloaded\nto update your KnownWord.json.", 
                               justify="left", bg=self.bg_color, fg=self.text_color, font=('Segoe UI', 10))
        instructions2.pack(side="left")
        
        process_btn = ttk.Button(step2_frame, text="Select & Process File", command=self.process_file)
        process_btn.pack(side="right", padx=10)
        
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
            if not self.script_path.exists():
                messagebox.showerror("Error", f"Script not found: {self.script_path}")
                return
            
            with open(self.script_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            self.root.clipboard_clear()
            self.root.clipboard_append(content)
            self.log("Script copied to clipboard!")
            messagebox.showinfo("Success", "JavaScript code copied to clipboard!\n\nPaste it into the browser console.")
        except Exception as e:
            self.log(f"Error copying script: {e}")
            messagebox.showerror("Error", f"Failed to copy script: {e}")

    def process_file(self):
        file_path = filedialog.askopenfilename(
            title="Select Migaku Database File",
            filetypes=[("SQLite Database", "*.db"), ("All Files", "*.*")]
        )
        
        if not file_path:
            return
            
        self.log(f"Processing: {os.path.basename(file_path)}")
        
        from app.path_utils import is_frozen
        
        try:
            # Run the converter script with UTF-8 env
            env = os.environ.copy()
            env["PYTHONUTF8"] = "1"
            
            if getattr(sys, 'frozen', False):
                # Frozen: Use the keyword mapped in app_entry.py
                cmd = [sys.executable, "convert_db", file_path]
            else:
                # Source: Use app_entry.py dispatcher
                project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                app_entry_path = os.path.join(project_root, "app_entry.py")
                cmd = [sys.executable, app_entry_path, "convert_db", file_path]
            
            # Run subprocess and capture output
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                                     text=True, encoding='utf-8', bufsize=1, env=env)
            
            for line in process.stdout:
                line = line.strip()
                if line:
                    self.log(line)
            
            process.wait()
            
            if process.returncode == 0:
                self.log("Success! KnownWord.json updated.")
                messagebox.showinfo("Success", "Database processed successfully!\nKnownWord.json has been updated and a backup of the old one was created.")
            else:
                self.log("Error during processing.")
                messagebox.showerror("Error", "An error occurred while processing the database. Check the log for details.")
                
        except Exception as e:
            self.log(f"Error: {e}")
            messagebox.showerror("Error", f"Failed to run converter: {e}")

def main():
    root = tk.Tk()
    app = MigakuImporterGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
