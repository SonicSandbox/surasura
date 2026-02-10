
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import sys
import shutil
import webbrowser
import glob

# Ensure package root is in sys.path
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.path_utils import get_user_file, get_icon_path, get_user_files_path

class FrequencyListGUI:
    def __init__(self, root, language='ja'):
        self.root = root
        self.language = language
        self.root.title(f"Surasura - Frequency List Manager ({language})")
        self.root.geometry("600x550")
        self.root.resizable(True, True)
        self.root.minsize(500, 450)
        
        # Bind Escape key to close
        self.root.bind("<Escape>", lambda e: self.root.destroy())
        
        # Set colors (Dark Theme by default to match app)
        self.bg_color = "#1e1e1e"
        self.surface_color = "#2d2d2d"
        self.text_color = "#e0e0e0"
        self.accent_color = "#bb86fc"
        self.secondary_color = "#03dac6"
        self.error_color = "#cf6679"
        
        self.root.configure(bg=self.bg_color)
        
        self.setup_styles()
        self.create_widgets()
        self.refresh_file_list()
        
        # Set Icon
        try:
            icon_path = get_icon_path()
            if os.path.exists(icon_path):
                self.icon_photo = tk.PhotoImage(file=icon_path)
                self.root.iconphoto(False, self.icon_photo)
        except Exception as e:
            print(f"Warning: Could not set icon: {e}")

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use('default')
        
        style.configure(".", background=self.bg_color, foreground=self.text_color, font=('Segoe UI', 10))
        style.configure("TFrame", background=self.bg_color)
        style.configure("TLabelframe", background=self.bg_color, bordercolor=self.surface_color)
        style.configure("TLabelframe.Label", background=self.bg_color, foreground=self.accent_color, font=('Segoe UI', 11, 'bold'))
        style.configure("TLabel", background=self.bg_color, foreground=self.text_color)
        style.configure("Header.TLabel", font=('Segoe UI', 16, 'bold'), foreground=self.secondary_color)
        style.configure("Link.TLabel", font=('Segoe UI', 10, 'underline'), foreground=self.accent_color)
        style.configure("Action.TButton", font=('Segoe UI', 10, 'bold'))
        
        # Listbox (tk widget) colors will be set directly
        
        # Button Styles
        style.configure("TButton", background=self.surface_color, foreground=self.text_color, borderwidth=0, padding=8)
        style.map("TButton",
            background=[('active', self.accent_color), ('pressed', self.accent_color)],
            foreground=[('active', self.bg_color), ('pressed', self.bg_color)]
        )

    def create_widgets(self):
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Header
        ttk.Label(main_frame, text="Frequency List Manager", style="Header.TLabel").pack(pady=(0, 15))

        # Instructions Frame
        instr_frame = ttk.LabelFrame(main_frame, text=" Instructions ", padding="15")
        instr_frame.pack(fill=tk.X, pady=(0, 15))

        instr_text = (
            "Download a CSV frequency list from here (or several):"
        )
        ttk.Label(instr_frame, text=instr_text).pack(anchor="w")

        # Link and Copy
        link_frame = ttk.Frame(instr_frame)
        link_frame.pack(fill=tk.X, pady=5)
        
        link_url = "https://jiten.moe/other"
        
        link_lbl = ttk.Label(link_frame, text=link_url, style="Link.TLabel", cursor="hand2")
        link_lbl.pack(side=tk.LEFT)
        link_lbl.bind("<Button-1>", lambda e: webbrowser.open(link_url))

        ttk.Label(instr_frame, text="Then add it/them into the User Files-folder.\n\nMagic happens.").pack(anchor="w", pady=(5, 0))

        # File Management Frame
        file_frame = ttk.LabelFrame(main_frame, text=" Manage Frequency Lists ", padding="15")
        file_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))

        # Buttons
        btn_box = ttk.Frame(file_frame)
        btn_box.pack(fill=tk.X, pady=(0, 10))
        
        add_btn = ttk.Button(btn_box, text="+ Add Frequency List(s)", style="Action.TButton", command=self.add_files)
        add_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        remove_btn = ttk.Button(btn_box, text="- Remove Selected", style="Action.TButton", command=self.remove_files)
        remove_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))

        # File List
        list_frame = ttk.Frame(file_frame)
        list_frame.pack(fill=tk.BOTH, expand=True)
        
        # Scrollbar
        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.file_listbox = tk.Listbox(list_frame, 
                                     bg=self.surface_color, 
                                     fg=self.text_color,
                                     selectbackground=self.accent_color,
                                     selectforeground=self.bg_color,
                                     relief=tk.FLAT,
                                     highlightthickness=1,
                                     highlightbackground=self.surface_color,
                                     yscrollcommand=scrollbar.set,
                                     height=6,
                                     font=('Consolas', 10))
        self.file_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.file_listbox.yview)

        # Note
        note_text = ("Note: The app already creates a frequency list based on your content. "
                     "This is visual enhancement to see how those words might be in general frequency lists")
        ttk.Label(main_frame, text=note_text, wraplength=550, foreground="#aaaaaa", font=('Segoe UI', 9, 'italic')).pack(anchor="w", pady=(0, 10))

        # Credit
        credit_frame = ttk.Frame(main_frame)
        credit_frame.pack(side=tk.BOTTOM, fill=tk.X)
        
        credit_lbl = ttk.Label(credit_frame, text="Credit to mattias", style="Link.TLabel", cursor="hand2")
        credit_lbl.pack(side=tk.RIGHT)
        credit_lbl.bind("<Button-1>", lambda e: webbrowser.open("https://github.com/mattias"))

    def copy_to_clipboard(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        messagebox.showinfo("Copied", "Link copied to clipboard!")

    def get_user_files_dir(self):
        return get_user_files_path(self.language)

    def refresh_file_list(self):
        self.file_listbox.delete(0, tk.END)
        target_dir = self.get_user_files_dir()
        
        if not os.path.exists(target_dir):
            os.makedirs(target_dir, exist_ok=True)
            
        # Only list files that match the analyzer's expectation
        files = glob.glob(os.path.join(target_dir, "frequency_list_*.csv"))
        
        for f in sorted(files):
            self.file_listbox.insert(tk.END, os.path.basename(f))

    def add_files(self):
        file_paths = filedialog.askopenfilenames(
            title="Select Frequency List CSVs",
            filetypes=[("CSV Files", "*.csv")]
        )
        
        if not file_paths:
            return
            
        target_dir = self.get_user_files_dir()
        if not os.path.exists(target_dir):
            os.makedirs(target_dir, exist_ok=True)
            
        count = 0
        for src in file_paths:
            try:
                base_name = os.path.basename(src)
                # Automatically add prefix if missing, so analyzer.py detects it
                if not base_name.startswith("frequency_list_"):
                    dest_name = f"frequency_list_{base_name}"
                else:
                    dest_name = base_name
                    
                dest = os.path.join(target_dir, dest_name)
                shutil.copy2(src, dest)
                count += 1
            except Exception as e:
                messagebox.showerror("Error", f"Failed to copy {os.path.basename(src)}:\n{e}")
        
        if count > 0:
            self.refresh_file_list()
            messagebox.showinfo("Success", f"Imported {count} frequency list(s).")

    def remove_files(self):
        selection = self.file_listbox.curselection()
        if not selection:
            messagebox.showwarning("Select File", "Please select a file to remove.")
            return
            
        files_to_remove = [self.file_listbox.get(i) for i in selection]
        
        if not messagebox.askyesno("Confirm Remove", f"Are you sure you want to remove {len(files_to_remove)} file(s)?"):
            return
            
        target_dir = self.get_user_files_dir()
        count = 0
        for fname in files_to_remove:
            try:
                path = os.path.join(target_dir, fname)
                if os.path.exists(path):
                    os.remove(path)
                    count += 1
            except Exception as e:
                messagebox.showerror("Error", f"Failed to remove {fname}:\n{e}")
                
        if count > 0:
            self.refresh_file_list()

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Surasura Frequency List Manager")
    parser.add_argument("--language", default="ja", help="Target language (ja, zh)")
    args = parser.parse_args()

    root = tk.Tk()
    app = FrequencyListGUI(root, language=args.language)
    root.mainloop()

if __name__ == "__main__":
    main()
