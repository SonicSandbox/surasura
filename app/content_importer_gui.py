import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import shutil
import os
import sys
import json
import subprocess

# Ensure package root is in sys.path
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.path_utils import get_user_file, ensure_data_setup, get_icon_path, get_data_path, get_user_files_path

# --- Constants & Theme ---
BG_COLOR = "#1e1e1e"
SURFACE_COLOR = "#2d2d2d"
ACCENT_COLOR = "#bb86fc"
TEXT_COLOR = "#ffffff"
ERROR_COLOR = "#cf6679"
SUCCESS_COLOR = "#03dac6"


class ContentImporterApp:
    def __init__(self, root, language='ja'):
        self.root = root
        self.language = language
        self.root.title(f"Surasura - Content Manager ({language})")
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
        ensure_data_setup(language)
        self.data_root = get_data_path(language)
        
        # State
        self.target_folder_var = tk.StringVar(value="HighPriority")
        self.target_folder_var.trace("w", self.on_folder_change)
        
        self.status_var = tk.StringVar(value="Ready")
        
        # Drag and Drop State
        self.tree: ttk.Treeview = None
        self.list_frame: ttk.Frame = None
        self.count_label: ttk.Label = None
        self._drag_item = None
        self._drag_start_y = 0
        self._drag_highlight = None
        self._last_drop_region = None
        self._last_drop_target = None

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
            background=[('active', BG_COLOR)],
            indicatorbackground=[('selected', ACCENT_COLOR), ('!selected', SURFACE_COLOR)],
            indicatorforeground=[('selected', BG_COLOR)]
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
            "HighPriority": ("NOW content", "(High priority - you will see in the next 2 weeks)"),
            "LowPriority": ("Soon", "(within the next 6 months)"),
            "GoalContent": ("6+ months", "(Aspirations or \"someday\" books)")
        }

        self.order_hints = {
            "HighPriority": "Order Matters a lot!",
            "LowPriority": "Order Matters a little, but not much",
            "GoalContent": "Order Doesn't matter"
        }

        # Radio Buttons
        for key, (label, sub) in self.folder_map.items():
            f = ttk.Frame(step1_frame)
            f.pack(anchor=tk.W, pady=2, padx=5)
            
            rb = ttk.Radiobutton(f, text=label, variable=self.target_folder_var, value=key)
            rb.pack(side=tk.LEFT)
            
            sub_lbl = ttk.Label(f, text=f"  {sub}", font=("Segoe UI", 9, "italic"), foreground="#888")
            sub_lbl.pack(side=tk.LEFT)
            # Make clicking the subtext also select the radio button
            sub_lbl.bind("<Button-1>", lambda e, k=key: self.target_folder_var.set(k))

        # Help Icon
        help_icon = tk.Label(step1_frame, text="?", font=("Segoe UI", 10, "bold"), 
                            bg=SURFACE_COLOR, fg=ACCENT_COLOR, cursor="hand2",
                            padx=6, pady=2, relief="flat")
        help_icon.place(relx=1.0, rely=1.0, anchor="se", x=-5, y=-5)
        
        tooltip_text = "Your vocab journey will prioritize words based on your immersion content, and how soon you'll see them"
        self.create_tooltip(help_icon, tooltip_text)

        # --- SECTION 2: FILE MANAGEMENT ---
        step2_frame = ttk.LabelFrame(main_frame, text=" 2. Manage Files ", padding="15")
        step2_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))

        # Toolbar
        btn_frame = ttk.Frame(step2_frame)
        btn_frame.pack(fill=tk.X, pady=(0, 10))
        
        add_btn = ttk.Button(btn_frame, text="+ Add Files", command=self.add_files)
        add_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        folder_btn = ttk.Button(btn_frame, text="+ Add Folder", command=self.add_folder)
        folder_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        del_btn = ttk.Button(btn_frame, text="- Remove Selected", command=self.remove_files)
        del_btn.pack(side=tk.LEFT)
        
        # Right Side Action Buttons
        refresh_btn = ttk.Button(btn_frame, text="↻", command=self.refresh_file_list, width=4)
        refresh_btn.pack(side=tk.RIGHT, padx=(0, 0))
        self.create_tooltip(refresh_btn, "Refresh file list")

        explorer_btn = ttk.Button(btn_frame, text="📂", command=self.open_data_folder, width=4)
        explorer_btn.pack(side=tk.RIGHT, padx=(5, 5))
        self.create_tooltip(explorer_btn, "Open current folder in Explorer")
        
        list_btn = ttk.Button(btn_frame, text="🏆", command=self.open_graduated_list, width=4)
        list_btn.pack(side=tk.RIGHT, padx=(5, 5))
        self.create_tooltip(list_btn, "Open Graduated Words List")

        graduate_btn = ttk.Button(btn_frame, text="🏆 Graduate", command=self.graduate_content)
        graduate_btn.pack(side=tk.RIGHT, padx=(5, 5))
        self.create_tooltip(graduate_btn, "Graduate Content (Move up priority flow and learn words)")

        # Hint label (Order matters...)
        hint_frame = ttk.Frame(step2_frame)
        hint_frame.pack(side=tk.TOP, fill=tk.X, pady=(0, 10))

        self.order_hint_label = ttk.Label(hint_frame, text=self.order_hints.get(self.target_folder_var.get(), ""), 
                                          foreground=ACCENT_COLOR, font=("Segoe UI", 9, "bold italic"))
        self.order_hint_label.pack(side=tk.LEFT)

        # Treeview with Scrollbar
        self.list_frame = ttk.Frame(step2_frame)
        self.list_frame.pack(fill=tk.BOTH, expand=True)
        
        # Define style for Treeview
        self.style.configure("Treeview", 
                             background=SURFACE_COLOR, 
                             foreground=TEXT_COLOR, 
                             fieldbackground=SURFACE_COLOR,
                             borderwidth=0,
                             font=("Segoe UI", 10))
        self.style.map("Treeview",
                       background=[('selected', ACCENT_COLOR)],
                       foreground=[('selected', BG_COLOR)])

        self.tree = ttk.Treeview(self.list_frame, 
                                 columns=("full_path",), 
                                 show="tree", 
                                 selectmode="extended")
        
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(self.list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.config(yscrollcommand=scrollbar.set)
        
        # DnD Events
        self.tree.bind("<Button-1>", self.on_drag_start)
        self.tree.bind("<B1-Motion>", self.on_drag_motion)
        self.tree.bind("<ButtonRelease-1>", self.on_drag_stop)
        
        # Move Hint
        hint_label = ttk.Label(step2_frame, text="Drag and move your files in the order you will immerse", foreground="#aaa", font=("Segoe UI", 9, "italic"))
        hint_label.pack(side=tk.LEFT, pady=(5,0))

        self.count_label = ttk.Label(step2_frame, text="0 files found", foreground="#888")
        self.count_label.pack(side=tk.RIGHT, pady=(5,0))

        status_bar = ttk.Label(main_frame, textvariable=self.status_var, foreground="#888")
        status_bar.pack(side=tk.LEFT, pady=(15, 0))

    def get_current_dir(self):
        folder_name = self.target_folder_var.get()
        return os.path.join(self.data_root, folder_name)

    def on_folder_change(self, *args):
        self.refresh_file_list()
        folder_key = self.target_folder_var.get()
        self.status_var.set(f"Switched to {folder_key}")
        
        # Update order hint
        if hasattr(self, 'order_hint_label'):
            self.order_hint_label.config(text=self.order_hints.get(folder_key, ""))

    def get_order_file(self, target_dir):
        return os.path.join(target_dir, "_order.json")

    def load_order(self, target_dir):
        order_file = self.get_order_file(target_dir)
        if os.path.exists(order_file):
            try:
                with open(order_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return {"order": data, "metadata": {}}
                    return data
            except Exception:
                return {"order": [], "metadata": {}}
        return {"order": [], "metadata": {}}

    def save_order(self, target_dir, data):
        order_file = self.get_order_file(target_dir)
        try:
            with open(order_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving order: {e}")

    def _get_ordered_items_in_dir(self, directory):
        """Returns a list of items in the directory, respecting _order.json if it exists."""
        try:
            if not os.path.isdir(directory): return []
            disk_items = os.listdir(directory)
        except Exception:
            return []
        
        disk_items = [f for f in disk_items if f != "_order.json"]
        data = self.load_order(directory)
        saved_order = data.get("order", [])
        metadata = data.get("metadata", {})
        
        # Filter disk_items by language
        # Items with no metadata tag are assumed to belong to the CURRENT language
        # (This fixed a bug where Chinese samples were hidden by default)
        filtered_disk_items = []
        for item in disk_items:
            item_lang = metadata.get(item, {}).get("lang", self.language)
            if item_lang == self.language:
                filtered_disk_items.append(item)
        
        final_list = []
        for item in saved_order:
            if item in filtered_disk_items:
                final_list.append(item)
                filtered_disk_items.remove(item)
        
        filtered_disk_items.sort() # Alphabetical for new/unsorted items
        final_list.extend(filtered_disk_items)
        
        return final_list

    def refresh_file_list(self):
        target_dir = self.get_current_dir()
        
        # 1. Store Expansion State (by path for reliability)
        expanded_paths = set()
        def capture_expanded(parent):
            for child in self.tree.get_children(parent):
                if self.tree.item(child, "open"):
                    vals = self.tree.item(child, "values")
                    if vals: expanded_paths.add(vals[0])
                capture_expanded(child)
        if self.tree: capture_expanded("")

        # Clear tree
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)
            
        # 2. Populate Treeview Recursively
        def populate_level(parent_node, directory):
            items = self._get_ordered_items_in_dir(directory)
            for item in items:
                path = os.path.join(directory, item)
                is_dir = os.path.isdir(path)
                
                # Check if this path was previously expanded
                should_open = path in expanded_paths
                
                node = self.tree.insert(parent_node, tk.END, text=item, values=(path,), open=should_open)
                if is_dir:
                    populate_level(node, path)

        populate_level("", target_dir)
            
        # Update total count
        total_items = self.get_tree_count("")
        if hasattr(self, 'count_label') and self.count_label:
            self.count_label.config(text=f"{total_items} items tracked")

    def get_tree_count(self, parent):
        count = 0
        for child in self.tree.get_children(parent):
            count += 1
            count += self.get_tree_count(child)
        return count

    def add_files(self):
        target_dir = self.get_current_dir()
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)

        # Start in Sample/Processed folder if it exists
        initial_dir = os.path.join(self.data_root, "Processed")
        if not os.path.exists(initial_dir):
            initial_dir = self.data_root

        filepaths = filedialog.askopenfilenames(
            title="Select Content Files",
            initialdir=initial_dir,
            filetypes=[
                ("All Supported", "*.txt *.md *.srt"),
                ("Text Files", "*.txt"),
                ("Markdown", "*.md"),
                ("Subtitles", "*.srt"),
                ("All Files", "*.*")
            ]
        )
        
        if filepaths:
            count = 0
            data = self.load_order(target_dir)
            order = data.get("order", [])
            metadata = data.get("metadata", {})
            for path in filepaths:
                try:
                    filename = os.path.basename(path)
                    dest = os.path.join(target_dir, filename)
                    shutil.copy2(path, dest)
                    if filename not in order:
                        order.append(filename)
                    # Tag with current language
                    metadata[filename] = {"lang": self.language}
                    count += 1
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to copy {filename}:\n{e}")
            
            data["order"] = order
            data["metadata"] = metadata
            self.save_order(target_dir, data)
            self.refresh_file_list()
            self.status_var.set(f"Added {count} files to {self.target_folder_var.get()} ({self.language})")
            messagebox.showinfo("Success", f"Successfully added {count} files.")

    def add_folder(self):
        target_dir = self.get_current_dir()
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)

        # Start in Sample/Processed folder if it exists
        initial_dir = os.path.join(self.data_root, "Processed")
        if not os.path.exists(initial_dir):
            initial_dir = self.data_root

        folder_path = filedialog.askdirectory(initialdir=initial_dir, title="Select Folder to Import")
        
        if not folder_path:
            return

        try:
            # Handle cases where path ends with slash (e.g. "C:/" or "D:/")
            folder_path = os.path.normpath(folder_path)
            folder_name = os.path.basename(folder_path)

            if not folder_name:
                messagebox.showerror("Error", "Invalid folder selected.")
                return
            
            dest = os.path.join(target_dir, folder_name)

            # Prevent importing into itself (recursive copy)
            if os.path.commonpath([folder_path, target_dir]) == os.path.normpath(folder_path):
                 messagebox.showerror("Error", f"Cannot import parent '{folder_name}' into its own child.")
                 return

            if os.path.exists(dest):
                if not messagebox.askyesno("Confirm Overwrite", f"Folder '{folder_name}' already exists in '{self.target_folder_var.get()}'.\nOverwrite it?"):
                    return
                if os.path.isdir(dest):
                    shutil.rmtree(dest)
                else:
                    os.remove(dest)
            
            shutil.copytree(folder_path, dest)
            
            # Update order
            data = self.load_order(target_dir)
            order = data.get("order", [])
            metadata = data.get("metadata", {})
            if folder_name not in order:
                order.append(folder_name)
            # Tag with current language
            metadata[folder_name] = {"lang": self.language}
            data["order"] = order
            data["metadata"] = metadata
            self.save_order(target_dir, data)
            
            self.refresh_file_list()
            self.status_var.set(f"Successfully added folder: {folder_name}")
            messagebox.showinfo("Success", f"Successfully added folder '{folder_name}'.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to copy folder '{folder_name}':\n{e}")

    def graduate_content(self):
        selected_items = self.tree.selection()
        if not selected_items:
            messagebox.showwarning("No Selection", "Please select items to graduate.")
            return

        current_folder = self.target_folder_var.get()
        destination_map = {
            "GoalContent": "LowPriority",
            "LowPriority": "HighPriority",
            "HighPriority": "Graduated"
        }
        
        if current_folder not in destination_map:
            messagebox.showinfo("Info", "Cannot graduate from this folder.")
            return
            
        dest_folder_name = destination_map[current_folder]
        dest_root = os.path.join(self.data_root, dest_folder_name)
        
        # Confirmation Logic
        if current_folder == "HighPriority":
            msg = (f"Graduate {len(selected_items)} items to '{dest_folder_name}'?\n\n"
                   "CAUTION: This will mark words as KNOWN based on the MOST RECENT analysis.\n"
                   "Words from these files found in the 'word_stats.json' report will be added to your GraduatedList.\n\n"
                   f"The files will be moved to: data/{self.language}/{dest_folder_name}")
        else:
            msg = f"Move {len(selected_items)} items from {current_folder} to {dest_folder_name}?"
            
        if not messagebox.askyesno("Confirm Graduation", msg):
            return

        # Ensure destination exists
        if not os.path.exists(dest_root):
            os.makedirs(dest_root)
            
        count = 0
        words_graduated = 0
        
        # Load Stats if High Priority
        stats = {}
        if current_folder == "HighPriority":
            try:
                # data_root is data/<lang>
                project_root = os.path.dirname(os.path.dirname(self.data_root))
                stats_path = os.path.join(project_root, "results", "word_stats.json")
                if os.path.exists(stats_path):
                    with open(stats_path, 'r', encoding='utf-8') as f:
                        stats = json.load(f)
                else:
                    print(f"Warning: word_stats.json not found at {stats_path}. Only moving files.")
            except Exception as e:
                print(f"Error loading stats: {e}")
                
        # Load Order Data
        source_order_data = self.load_order(self.get_current_dir())
        dest_order_data = self.load_order(dest_root)
        
        for item_id in selected_items:
            item_text = self.tree.item(item_id, "text")
            item_values = self.tree.item(item_id, "values")
            if not item_values: continue
            
            source_path = item_values[0]
            if not os.path.exists(source_path): continue
            
            filename = os.path.basename(source_path)
            dest_path = os.path.join(dest_root, filename)
            
            try:
                # 1. Graduate Words Logic (High Priority only)
                if current_folder == "HighPriority" and stats:
                    # Find all filenames associated with this item (could be folder)
                    filenames_to_match = set()
                    if os.path.isfile(source_path):
                        filenames_to_match.add(os.path.basename(source_path))
                    else:
                        for root, dirs, files in os.walk(source_path):
                            for f in files:
                                filenames_to_match.add(f)
                    
                    file_words = []
                    for key, data in stats.items():
                        sources = data.get("sources", [])
                        # Match if any of our filenames are in the sources list
                        if any(f in sources for f in filenames_to_match):
                            parts = key.split("|")
                            if len(parts) >= 1:
                                file_words.append(parts[0]) # Add lemma
                    
                    if file_words:
                        file_words = sorted(list(set(file_words)))
                        
                        # Correct path resolution for User Files
                        project_root = os.path.dirname(os.path.dirname(self.data_root))
                        user_files_dir = os.path.join(project_root, "User Files", self.language)
                        if not os.path.exists(user_files_dir):
                             os.makedirs(user_files_dir)
                        grad_list_path = os.path.join(user_files_dir, "GraduatedList.txt")
                        
                        with open(grad_list_path, 'a', encoding='utf-8') as f:
                            f.write(f"\n# Source: {filename} ({len(file_words)} words graduated)\n")
                            for w in file_words:
                                f.write(f"{w}\n")
                        words_graduated += len(file_words)

                # 2. Move File
                shutil.move(source_path, dest_path)
                
                # 3. Update Orders
                # Remove from source
                if item_text in source_order_data.get("order", []):
                    source_order_data["order"].remove(item_text)
                if item_text in source_order_data.get("metadata", {}):
                    del source_order_data["metadata"][item_text]
                    
                # Add to dest
                if item_text not in dest_order_data.get("order", []):
                    dest_order_data["order"].append(item_text)
                dest_order_data.setdefault("metadata", {})[item_text] = {"lang": self.language}
                
                count += 1
                
            except Exception as e:
                messagebox.showerror("Error", f"Failed to graduate {filename}:\n{e}")
        
        # Save Orders
        self.save_order(self.get_current_dir(), source_order_data)
        self.save_order(dest_root, dest_order_data)
        
        self.refresh_file_list()
        status_msg = f"Moved {count} items to {dest_folder_name}."
        if words_graduated > 0:
            status_msg += f" Added {words_graduated} words to GraduatedList."
        self.status_var.set(status_msg)
        messagebox.showinfo("Success", status_msg)

    def remove_files(self):
        selected_items = self.tree.selection()
        if not selected_items:
            messagebox.showwarning("No Selection", "Please select items to remove.")
            return

        confirm = messagebox.askyesno(
            "Confirm Deletion", 
            f"Are you sure you want to delete {len(selected_items)} selected items and their contents?\nThis cannot be undone."
        )
        
        if confirm:
            target_dir = self.get_current_dir()
            count = 0
            
            # We only remove root-level items from the order file
            order_data = self.load_order(target_dir) # Load FULL object
            order = order_data.get("order", [])
            metadata = order_data.get("metadata", {})
            
            for item_id in selected_items:
                item_text = self.tree.item(item_id, "text")
                item_values = self.tree.item(item_id, "values")
                if not item_values: continue
                path = item_values[0]
                
                try:
                    if os.path.isfile(path):
                        os.remove(path)
                    elif os.path.isdir(path):
                        shutil.rmtree(path)
                    
                    # If it was a root item, remove from order
                    if item_text in order:
                        order.remove(item_text)
                    if item_text in metadata:
                        del metadata[item_text]
                        
                    count += 1
                except Exception as e:
                    print(f"Error deleting {path}: {e}")
            
            order_data["order"] = order
            order_data["metadata"] = metadata
            self.save_order(target_dir, order_data)
            
            self.refresh_file_list()
            self.status_var.set(f"Removed {count} items.")

    def _get_drop_region(self, item, y):
        """Determine if drop is above, below, or inside the target item."""
        bbox = self.tree.bbox(item)
        if not bbox: return "inside"
        
        h = bbox[3]
        offset_y = y - bbox[1]
        
        region = "inside"
        if offset_y < h * 0.25: region = "above"
        elif offset_y > h * 0.75: region = "below"
        
        # Files cannot accept 'inside' drops
        path = self.tree.item(item, "values")[0]
        if not os.path.isdir(path):
            if region == "inside":
                 region = "below" if offset_y > h / 2 else "above"
        
        return region

    def on_drag_start(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            self._drag_item = item
            self._drag_start_y = event.y

    def on_drag_motion(self, event):
        if not self._drag_item:
            return

        target_item = self.tree.identify_row(event.y)
        self.tree.scan_dragto(event.x, event.y)
        
        # Clean up 'inside' highlight
        if hasattr(self, '_drag_highlight') and self._drag_highlight:
             try:
                self.tree.item(self._drag_highlight, tags=())
             except: pass
             self._drag_highlight = None

        if not target_item:
            return

        region = self._get_drop_region(target_item, event.y)
        
        # Prevent "inside" self
        if target_item == self._drag_item and region == "inside":
            region = "below"

        self._last_drop_region = region
        self._last_drop_target = target_item

        # Visual Feedback: Only highlight folders for "inside" drops
        if region == "inside":
            self.tree.tag_configure('drop_target', background=ACCENT_COLOR, foreground=BG_COLOR)
            self.tree.item(target_item, tags=('drop_target',))
            self._drag_highlight = target_item

    def on_drag_stop(self, event):
        # Clean up visuals
        if hasattr(self, '_drag_highlight') and self._drag_highlight:
            self.tree.item(self._drag_highlight, tags=())
            self._drag_highlight = None
            
        target_item = self.tree.identify_row(event.y)
        source_item = getattr(self, "_drag_item", None)
        
        if not source_item or not target_item:
            return

        source_parent = self.tree.parent(source_item)
        
        # Determine region using helper
        region = self._get_drop_region(target_item, event.y)
            
        if source_item == target_item: return

        # ACTION: RE-PARENT (Move Into)
        if region == "inside":
             target_parent = target_item # The folder IS the parent
             
             # Move on disk
             source_path = self.tree.item(source_item, "values")[0]
             dest_dir = self.tree.item(target_item, "values")[0]
             
             if not os.path.isdir(dest_dir):
                 return # Should highlight generic error, but UI logic prevents this path usually
                 
             filename = os.path.basename(source_path)
             dest_path = os.path.join(dest_dir, filename)
             
             try:
                 shutil.move(source_path, dest_path)
                 self.tree.move(source_item, target_item, "end")
             except Exception as e:
                 messagebox.showerror("Error", f"Failed to move: {e}")
                 
        # ACTION: RE-ORDER (Insert Above/Below)
        else:
             target_parent = self.tree.parent(target_item)
             
             # We only support reordering if they share the same parent for now?
             # Or we treat 'above/below' as 'move to same parent as target'.
             # Let's support moving to target's parent.
             
             if source_parent != target_parent:
                 # Move on disk first
                 source_path = self.tree.item(source_item, "values")[0]
                 if target_parent == "":
                     dest_dir = self.get_current_dir()
                 else:
                     dest_dir = self.tree.item(target_parent, "values")[0]
                     
                 filename = os.path.basename(source_path)
                 dest_path = os.path.join(dest_dir, filename)
                 
                 try:
                     if os.path.abspath(source_path) != os.path.abspath(dest_path):
                         shutil.move(source_path, dest_path)
                 except Exception as e:
                     messagebox.showerror("Error", f"Failed to move: {e}")
                     return

             # UI Move
             index = self.tree.index(target_item)
             if region == "below":
                 index += 1
             self.tree.move(source_item, target_parent, index)

        # Save Order logic
        self._save_level_order(source_parent)
        if hasattr(self, '_last_drop_target'):
             new_parent = self.tree.parent(source_item)
             if new_parent != source_parent:
                 self._save_level_order(new_parent)
        
        self.refresh_file_list()
        self.status_var.set("Order updated.")

    def _save_level_order(self, parent_node):
        """Saves the current visible order of a node's children to its directory's _order.json"""
        if parent_node == "":
            directory = self.get_current_dir()
        else:
            directory = self.tree.item(parent_node, "values")[0]
            
        children = self.tree.get_children(parent_node)
        new_order_list = [self.tree.item(c, "text") for c in children]
        
        data = self.load_order(directory)
        data["order"] = new_order_list
        # Metadata is preserved as we only update the order flat list
        self.save_order(directory, data)

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

    def open_graduated_list(self):
        path = os.path.join(get_user_files_path(self.language), "GraduatedList.txt")
        if not os.path.exists(path):
            # Ensure folder exists
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write("# Graduated Words (added automatically when files graduate)\n")
        
        if sys.platform == 'win32':
            os.startfile(path)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', path])
        else:
            subprocess.Popen(['xdg-open', path])

    def create_tooltip(self, widget, text):
        def show_tip(event):
            tip = tk.Toplevel()
            tip.wm_overrideredirect(True)
            tip.wm_geometry(f"+{event.x_root+15}+{event.y_root+15}")
            tip.configure(bg=SURFACE_COLOR)
            label = tk.Label(tip, text=text, bg=SURFACE_COLOR, fg=TEXT_COLOR, 
                             font=("Segoe UI", 9), padx=8, pady=5, 
                             relief="solid", borderwidth=1, highlightthickness=0,
                             wraplength=250, justify=tk.LEFT)
            label.pack()
            widget.tip = tip

        def hide_tip(event):
            if hasattr(widget, "tip"):
                widget.tip.destroy()

        widget.bind("<Enter>", show_tip)
        widget.bind("<Leave>", hide_tip)

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Surasura Content Importer")
    parser.add_argument("--language", default="ja", help="Target language (ja, zh)")
    args = parser.parse_args()

    root = tk.Tk()
    app = ContentImporterApp(root, language=args.language)
    root.mainloop()

if __name__ == "__main__":
    main()
