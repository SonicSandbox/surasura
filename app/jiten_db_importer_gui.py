import tkinter as tk
import os
import sys
from pathlib import Path
from tkinter import messagebox, ttk
import subprocess

# Ensure package root is in sys.path
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.path_utils import get_user_file, get_resource

class JitenImporterGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Surasura - Jiten Known-Word Importer")
        self.root.geometry("600x450")
        self.root.resizable(True, True)
        self.root.minsize(500, 350)
        
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
        header = tk.Label(self.root, text="Jiten Known-Word Importer", font=('Segoe UI', 16, 'bold'), 
                         bg=self.bg_color, fg=self.text_color, pady=15)
        header.pack()
        
        # Instructions Frame
        instructions_frame = tk.LabelFrame(self.root, text="Step 1: Get Your API Key", font=('Segoe UI', 11, 'bold'),
                                          bg=self.bg_color, fg=self.accent_color, padx=20, pady=15)
        instructions_frame.pack(fill="x", padx=30, pady=5)
        
        instructions_text = (
            "1. Go to https://jiten.moe/settings/api\n"
            "2. Copy your API Key\n"
            "3. Paste it below"
        )
        
        instructions_label = tk.Label(instructions_frame, 
                                     text=instructions_text, 
                                     justify="left", bg=self.bg_color, fg=self.text_color, 
                                     font=('Segoe UI', 10))
        instructions_label.pack(anchor="w", pady=(0, 10))
        
        # API Key Input Frame
        api_frame = tk.LabelFrame(self.root, text="Step 2: Enter API Key", font=('Segoe UI', 11, 'bold'),
                                 bg=self.bg_color, fg=self.accent_color, padx=20, pady=15)
        api_frame.pack(fill="x", padx=30, pady=10)
        
        # Label
        api_label = tk.Label(api_frame, text="API Key:", bg=self.bg_color, fg=self.text_color, font=('Segoe UI', 10))
        api_label.pack(anchor="w", pady=(0, 5))
        
        # Entry
        self.api_key_var = tk.StringVar()
        self.api_key_entry = tk.Entry(api_frame, textvariable=self.api_key_var, font=('Consolas', 10),
                                      show="*", width=40)
        self.api_key_entry.pack(fill="x", pady=(0, 10))
        
        # Show/Hide toggle
        self.show_key_var = tk.BooleanVar(value=False)
        show_btn = ttk.Checkbutton(api_frame, text="Show API Key", variable=self.show_key_var,
                                  command=self.toggle_show_key)
        show_btn.pack(anchor="w", pady=(0, 10))
        
        # Import Button
        btn_frame = tk.Frame(api_frame, bg=self.bg_color)
        btn_frame.pack(fill="x")
        
        import_btn = ttk.Button(btn_frame, text="Fetch & Import", command=self.fetch_and_import)
        import_btn.pack(side="left", expand=True, fill="x")
        
        # Status Log
        log_frame = tk.Frame(self.root, bg=self.bg_color)
        log_frame.pack(fill="both", expand=True, padx=30, pady=10)
        
        log_label = tk.Label(log_frame, text="Status Log:", bg=self.bg_color, fg=self.text_color, 
                            font=('Segoe UI', 10, 'bold'))
        log_label.pack(anchor="w", pady=(0, 5))
        
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

    def toggle_show_key(self):
        if self.show_key_var.get():
            self.api_key_entry.config(show="")
        else:
            self.api_key_entry.config(show="*")

    def fetch_and_import(self):
        api_key = self.api_key_var.get().strip()
        
        if not api_key:
            messagebox.showerror("Error", "Please enter your Jiten API key.")
            return
        
        self.log("Fetching vocabulary from Jiten API...")
        
        try:
            # Run the converter script with UTF-8 env
            env = os.environ.copy()
            env["PYTHONUTF8"] = "1"
            
            if getattr(sys, 'frozen', False):
                # Frozen
                cmd = [sys.executable, "convert_jiten", api_key]
            else:
                # Source
                project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                app_entry_path = os.path.join(project_root, "app_entry.py")
                cmd = [sys.executable, app_entry_path, "convert_jiten", api_key]
            
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
                messagebox.showinfo("Success", "Jiten vocabulary imported successfully!\nKnownWord.json has been updated.")
            else:
                self.log("Error during processing.")
                messagebox.showerror("Error", "An error occurred while processing. Check the log.")
                
        except Exception as e:
            self.log(f"Error: {e}")
            messagebox.showerror("Error", f"Failed to run importer: {e}")

def main():
    root = tk.Tk()
    app = JitenImporterGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
