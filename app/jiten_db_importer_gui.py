import tkinter as tk
import os
import sys
from pathlib import Path
from tkinter import messagebox, ttk
import subprocess
import webbrowser

# Ensure package root is in sys.path
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.path_utils import get_user_file, get_resource

class JitenImporterGUI:
    def __init__(self, root, language='ja'):
        self.root = root
        self.language = language
        self.root.title(f"Surasura - Jiten Known-Word Importer ({language})")
        self.root.geometry("600x450")
        self.root.resizable(True, True)
        self.root.minsize(500, 350)
        
        # Bind Escape key to close
        self.root.bind("<Escape>", lambda e: self.root.destroy())
        
        # Set colors and styles
        self.bg_color = "#1e1e1e"
        self.surface_color = "#2d2d2d"
        self.text_color = "#e0e0e0"
        self.accent_color = "#bb86fc"
        self.root.configure(bg=self.bg_color)
        
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("TButton", background=self.surface_color, foreground=self.text_color, borderwidth=0, padding=8)
        style.map("TButton",
            background=[('active', self.accent_color)],
            foreground=[('active', self.bg_color)]
        )
        
        style.configure("TFrame", background=self.bg_color)
        style.configure("TLabelframe", background=self.bg_color, bordercolor=self.surface_color)
        style.configure("TLabelframe.Label", background=self.bg_color, foreground=self.accent_color, font=('Segoe UI', 11, 'bold'))
        style.configure("TLabel", background=self.bg_color, foreground=self.text_color)
        style.configure("Link.TLabel", font=('Segoe UI', 10, 'underline'), foreground=self.accent_color, background=self.bg_color)
        style.configure("TCheckbutton", background=self.bg_color, foreground=self.text_color)
        style.map("TCheckbutton",
            background=[('active', self.bg_color)],
            foreground=[('active', self.accent_color)]
        )
        
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
                         bg=self.bg_color, fg="#03dac6", pady=10) # Reduced pady 15 -> 10
        header.pack()
        
        # Instructions Frame
        instructions_frame = ttk.LabelFrame(self.root, text=" Step 1: Get Your API Key ", padding="15")
        instructions_frame.pack(fill="x", padx=30, pady=5)
        
        instructions_text = (
            "1. Go to https://jiten.moe/settings/api\n"
            "2. Copy your API Key\n"
            "3. Paste it below"
        )
        
        link_url = "https://jiten.moe/settings/api"
        instructions_label = ttk.Label(instructions_frame, 
                                     text=instructions_text, 
                                     justify="left")
        instructions_label.pack(anchor="w", pady=(0, 5))
        
        link_lbl = ttk.Label(instructions_frame, text="jiten.moe/settings/api", style="Link.TLabel", cursor="hand2")
        link_lbl.pack(anchor="w", pady=(0, 10))
        
        link_lbl.bind("<Button-1>", lambda e: webbrowser.open(link_url))
        
        # Credit Label at bottom
        credit_frame = ttk.Frame(self.root)
        credit_frame.pack(side="bottom", fill="x", pady=(5, 15), padx=30)
        
        credit_lbl = ttk.Label(credit_frame, text="Credit to mattias", style="Link.TLabel", cursor="hand2")
        credit_lbl.pack(side="right")
        credit_lbl.bind("<Button-1>", lambda e: webbrowser.open("https://github.com/mattias"))
        
        # API Key Input Frame
        api_frame = ttk.LabelFrame(self.root, text=" Step 2: Enter API Key ", padding="15")
        api_frame.pack(fill="x", padx=30, pady=10)
        
        # Label
        api_label = tk.Label(api_frame, text="API Key:", bg=self.bg_color, fg=self.text_color, font=('Segoe UI', 10))
        api_label.pack(anchor="w", pady=(0, 5))
        
        # Entry
        self.api_key_var = tk.StringVar()
        self.api_key_entry = tk.Entry(api_frame, textvariable=self.api_key_var, font=('Consolas', 10),
                                      show="*", width=40, bg=self.surface_color, fg=self.text_color, 
                                      insertbackground=self.text_color, relief="flat")
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
        
        self.log_text = tk.Text(log_frame, height=5, font=('Consolas', 9), bg="#121212", fg="#888", 
                                 padx=10, pady=10, state="disabled", borderwidth=0,
                                 highlightthickness=1, highlightbackground=self.surface_color)
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
                cmd = [sys.executable, "convert_jiten", api_key, "--language", self.language]
            else:
                # Source
                project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                app_entry_path = os.path.join(project_root, "app_entry.py")
                cmd = [sys.executable, app_entry_path, "convert_jiten", api_key, "--language", self.language]
            
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
    import argparse
    parser = argparse.ArgumentParser(description="Surasura Jiten Importer")
    parser.add_argument("--language", default="ja", help="Target language (ja, zh)")
    args = parser.parse_args()

    root = tk.Tk()
    app = JitenImporterGUI(root, language=args.language)
    root.mainloop()

if __name__ == "__main__":
    main()
