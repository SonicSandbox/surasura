import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import shutil
import os
import subprocess
import sys
from app.path_utils import get_user_file, ensure_data_setup, get_icon_path

# --- Constants & Theme ---
BG_COLOR = "#1e1e1e"
SURFACE_COLOR = "#2d2d2d"
ACCENT_COLOR = "#bb86fc"
TEXT_COLOR = "#ffffff"
ERROR_COLOR = "#cf6679"
SUCCESS_COLOR = "#03dac6"

class ContentImporterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Surasura - Content Manager")
        self.root.geometry("650x700")  # Expanded size
        self.root.minsize(600, 600)
        self.root.configure(bg=BG_COLOR)
        
        # Bind Escape key to close
        self.root.bind("<Escape>", lambda e: self.root.destroy())
        self.style = ttk.Style()
        self.apply_dark_theme()
        
        # Set Icon
        try:
            icon_path = get_icon_path()
            if os.path.exists(icon_path):
                self.icon_photo = tk.PhotoImage(file=icon_path)
                self.root.iconphoto(False, self.icon_photo)
        except Exception:
            pass

        # Data Setup
        ensure_data_setup()
        self.data_root = get_user_file("data")
        
        # State
        self.target_folder_var = tk.StringVar(value="HighPriority")
        self.target_folder_var.trace("w", self.on_folder_change)
        
        self.status_var = tk.StringVar(value="Ready")

        self.setup_ui()
        self.refresh_file_list()

    def apply_dark_theme(self):
        self.style.theme_use('clam')
        
        self.style.configure(".", 
            background=BG_COLOR, 
            foreground=TEXT_COLOR, 
            fieldbackground=SURFACE_COLOR,
            troughcolor=BG_COLOR,
            selectbackground=ACCENT_COLOR,
            selectforeground=BG_COLOR
        )
        
        # Labelframes
        self.style.configure("TLabelframe", 
            background=BG_COLOR, 
            foreground=ACCENT_COLOR, 
            bordercolor=SURFACE_COLOR
        )
        self.style.configure("TLabelframe.Label", 
            background=BG_COLOR, 
            foreground=ACCENT_COLOR,
            font=("Segoe UI", 11, "bold")
        )

        # Header
        self.style.configure("Header.TLabel", 
            font=("Segoe UI", 16, "bold"), 
            foreground=SUCCESS_COLOR,
            background=BG_COLOR
        )

        # Buttons
        self.style.configure("TButton", 
            background=SURFACE_COLOR, 
            foreground=TEXT_COLOR, 
            borderwidth=0, 
            focuscolor=ACCENT_COLOR,
            padding=6
        )
        self.style.map("TButton",
            background=[('active', ACCENT_COLOR)],
            foreground=[('active', BG_COLOR)]
        )
        
        # Radiobuttons
        self.style.configure("TRadiobutton", 
            background=BG_COLOR, 
            foreground=TEXT_COLOR,
            font=("Segoe UI", 10)
        )
        self.style.map("TRadiobutton",
            foreground=[('active', ACCENT_COLOR)],
            background=[('active', BG_COLOR)]
        )

    def setup_ui(self):
        main_frame = ttk.Frame(self.root, padding="25")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Header
        header = ttk.Label(main_frame, text="Content Manager", style="Header.TLabel")
        header.pack(pady=(0, 10))

        # Description
        desc = ttk.Label(main_frame, text="Simplicity is Mastery.\nManage your immersion content here.", 
                         justify=tk.CENTER, foreground="#aaaaaa")
        desc.pack(pady=(0, 20))

        # SECTION 1: PRIORITY SELECTION
        step1_frame = ttk.LabelFrame(main_frame, text=" 1. Select Section ", padding="15")
        step1_frame.pack(fill=tk.X, pady=(0, 20))

        # Custom Labels map with full tab
        self.folder_map = {
            "HighPriority": "High Priority\t(What will you see next week?)",
            "LowPriority": "Low Priority\t(In the next month)",
            "GoalContent": "Goal Content\t(Your ambitious Goal)"
        }

        # Radio Buttons
        for key, text in self.folder_map.items():
            rb = ttk.Radiobutton(step1_frame, text=text, variable=self.target_folder_var, value=key)
            rb.pack(anchor=tk.W, pady=5, padx=5)

        # --- SECTION 2: FILE MANAGEMENT ---
        step2_frame = ttk.LabelFrame(main_frame, text=" 2. Manage Files ", padding="15")
        step2_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))

        # Toolbar
        btn_frame = ttk.Frame(step2_frame)
        btn_frame.pack(fill=tk.X, pady=(0, 10))
        
        add_btn = ttk.Button(btn_frame, text="+ Add Files", command=self.add_files)
        add_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        del_btn = ttk.Button(btn_frame, text="- Remove Selected", command=self.remove_files)
        del_btn.pack(side=tk.LEFT)
        
        refresh_btn = ttk.Button(btn_frame, text="↻ Refresh", command=self.refresh_file_list)
        refresh_btn.pack(side=tk.RIGHT)
        
        explorer_btn = ttk.Button(btn_frame, text="📂 Open in Explorer", command=self.open_data_folder)
        explorer_btn.pack(side=tk.RIGHT, padx=(0, 10))

        # Listbox with Scrollbar
        list_frame = ttk.Frame(step2_frame)
        list_frame.pack(fill=tk.BOTH, expand=True)
        
        self.file_listbox = tk.Listbox(list_frame, 
                                       bg=SURFACE_COLOR, 
                                       fg=TEXT_COLOR, 
                                       selectbackground=ACCENT_COLOR, 
                                       selectforeground=BG_COLOR,
                                       borderwidth=1, 
                                       highlightthickness=0, 
                                       height=15,
                                       font=("Consolas", 10),
                                       selectmode=tk.EXTENDED) # Multiple selection
        self.file_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.file_listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.file_listbox.config(yscrollcommand=scrollbar.set)
        
        # Hint label
        self.count_label = ttk.Label(step2_frame, text="0 files found", foreground="#888")
        self.count_label.pack(anchor=tk.E, pady=(5,0))

        # --- FOOTER ---
        action_frame = ttk.Frame(main_frame)
        action_frame.pack(fill=tk.X, pady=(10, 0))

        ttk.Button(action_frame, text="Open Data Folder", command=self.open_data_folder).pack(side=tk.RIGHT)

        # Status Bar
        status_bar = ttk.Label(main_frame, textvariable=self.status_var, foreground="#888")
        status_bar.pack(side=tk.LEFT, pady=(15, 0))

    def get_current_dir(self):
        folder_name = self.target_folder_var.get()
        return os.path.join(self.data_root, folder_name)

    def on_folder_change(self, *args):
        self.refresh_file_list()
        self.status_var.set(f"Switched to {self.target_folder_var.get()}")

    def refresh_file_list(self):
        target_dir = self.get_current_dir()
        self.file_listbox.delete(0, tk.END)
        
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)
            
        files = [f for f in os.listdir(target_dir) if os.path.isfile(os.path.join(target_dir, f))]
        
        for f in files:
            self.file_listbox.insert(tk.END, f)
            
        self.count_label.config(text=f"{len(files)} files found")

    def add_files(self):
        target_dir = self.get_current_dir()
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)

        filepaths = filedialog.askopenfilenames(
            title="Select Content Files",
            filetypes=[
                ("All Supported", "*.txt *.md *.epub *.srt"),
                ("Text Files", "*.txt"),
                ("Markdown", "*.md"),
                ("EPUB Books", "*.epub"),
                ("Subtitles", "*.srt"),
                ("All Files", "*.*")
            ]
        )
        
        if filepaths:
            count = 0
            for path in filepaths:
                try:
                    filename = os.path.basename(path)
                    dest = os.path.join(target_dir, filename)
                    shutil.copy2(path, dest)
                    count += 1
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to copy {filename}:\n{e}")
            
            self.refresh_file_list()
            self.status_var.set(f"Added {count} files to {self.target_folder_var.get()}")
            messagebox.showinfo("Success", f"Successfully added {count} files.")

    def remove_files(self):
        selected_indices = self.file_listbox.curselection()
        if not selected_indices:
            messagebox.showwarning("No Selection", "Please select files to remove.")
            return

        files_to_remove = [self.file_listbox.get(i) for i in selected_indices]
        
        confirm = messagebox.askyesno(
            "Confirm Deletion", 
            f"Are you sure you want to delete {len(files_to_remove)} files?\nThis cannot be undone."
        )
        
        if confirm:
            target_dir = self.get_current_dir()
            count = 0
            for filename in files_to_remove:
                try:
                    path = os.path.join(target_dir, filename)
                    os.remove(path)
                    count += 1
                except Exception as e:
                    print(f"Error deleting {filename}: {e}")
            
            self.refresh_file_list()
            self.status_var.set(f"Removed {count} files.")

    def open_data_folder(self):
        path = self.get_current_dir()
        if not os.path.exists(path):
            os.makedirs(path)
            
        if sys.platform == 'win32':
            os.startfile(path)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', path])
        else:
            subprocess.Popen(['xdg-open', path])

if __name__ == "__main__":
    root = tk.Tk()
    app = ContentImporterApp(root)
    root.mainloop()
