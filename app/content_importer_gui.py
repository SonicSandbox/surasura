import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import shutil
import os
import subprocess
import sys
import json
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
        
        folder_btn = ttk.Button(btn_frame, text="+ Add Folder", command=self.add_folder)
        folder_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        del_btn = ttk.Button(btn_frame, text="- Remove Selected", command=self.remove_files)
        del_btn.pack(side=tk.LEFT)
        
        refresh_btn = ttk.Button(btn_frame, text="↻ Refresh", command=self.refresh_file_list)
        refresh_btn.pack(side=tk.RIGHT)
        
        explorer_btn = ttk.Button(btn_frame, text="📂 Open in Explorer", command=self.open_data_folder)
        explorer_btn.pack(side=tk.RIGHT, padx=(0, 10))

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
        
        # Hint label
        hint_label = ttk.Label(step2_frame, text="Drag and drop your files in the order you will immerse", foreground="#aaa", font=("Segoe UI", 9, "italic"))
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
        self.status_var.set(f"Switched to {self.target_folder_var.get()}")

    def get_order_file(self, target_dir):
        return os.path.join(target_dir, "_order.json")

    def load_order(self, target_dir):
        order_file = self.get_order_file(target_dir)
        if os.path.exists(order_file):
            try:
                with open(order_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    def save_order(self, target_dir, order):
        order_file = self.get_order_file(target_dir)
        try:
            with open(order_file, 'w', encoding='utf-8') as f:
                json.dump(order, f, indent=2, ensure_ascii=False)
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
        saved_order = self.load_order(directory)
        
        final_list = []
        for item in saved_order:
            if item in disk_items:
                final_list.append(item)
                disk_items.remove(item)
        
        disk_items.sort() # Alphabetical for new/unsorted items
        final_list.extend(disk_items)
        
        # Sync back if list was modified by additions/removals
        if len(saved_order) != len(final_list):
            self.save_order(directory, final_list)
            
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
            order = self.load_order(target_dir)
            for path in filepaths:
                try:
                    filename = os.path.basename(path)
                    dest = os.path.join(target_dir, filename)
                    shutil.copy2(path, dest)
                    if filename not in order:
                        order.append(filename)
                    count += 1
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to copy {filename}:\n{e}")
            
            self.save_order(target_dir, order)
            self.refresh_file_list()
            self.status_var.set(f"Added {count} files to {self.target_folder_var.get()}")
            messagebox.showinfo("Success", f"Successfully added {count} files.")

    def add_folder(self):
        target_dir = self.get_current_dir()
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)

        # Start in Sample/Processed folder if it exists
        initial_dir = os.path.join(self.data_root, "Processed")
        if not os.path.exists(initial_dir):
            initial_dir = self.data_root

        folder_path = filedialog.askdirectory(title="Select Folder to Import", initialdir=initial_dir)
        
        if folder_path:
            try:
                # Handle cases where path ends with slash (e.g. "C:/" or "D:/")
                folder_path = os.path.normpath(folder_path)
                folder_name = os.path.basename(folder_path)

                if not folder_name:
                    messagebox.showerror("Error", "Cannot import a root drive or empty folder name.\nPlease select a subdirectory.")
                    return
                
                dest = os.path.join(target_dir, folder_name)

                #Prevent importing into itself (recursive copy)
                if os.path.commonpath([folder_path, target_dir]) == os.path.normpath(folder_path):
                     messagebox.showerror("Error", "Cannot import a parent folder into its own child.")
                     return

                # Prevent overwriting the target directory itself (redundant but safe)
                if os.path.abspath(dest) == os.path.abspath(target_dir):
                     messagebox.showerror("Error", "Invalid destination. Cannot overwrite the target folder.")
                     return
                
                if os.path.exists(dest):
                    if not messagebox.askyesno("Confirm Overwrite", f"Folder '{folder_name}' already exists in '{self.target_folder_var.get()}'.\nOverwrite it?"):
                        return
                    # Safe removal: verify it's inside target_dir before deleting
                    if os.path.dirname(os.path.abspath(dest)) == os.path.abspath(target_dir):
                        if os.path.isdir(dest):
                            shutil.rmtree(dest)
                        else:
                            os.remove(dest) # In case it was a file
                
                shutil.copytree(folder_path, dest)
                
                # Update order
                order = self.load_order(target_dir)
                if folder_name not in order:
                    order.append(folder_name)
                self.save_order(target_dir, order)
                
                self.refresh_file_list()
                self.status_var.set(f"Added folder '{folder_name}'")
                messagebox.showinfo("Success", f"Successfully added folder '{folder_name}'.")
            except Exception as e:
                # If copy failed, try to clean up if we created an empty folder?
                # For now just show error.
                messagebox.showerror("Error", f"Failed to copy folder:\n{e}")

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
            order = self.load_order(target_dir)
            
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
                    count += 1
                except Exception as e:
                    print(f"Error deleting {path}: {e}")
            
            self.save_order(target_dir, order)
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
        order = [self.tree.item(c, "text") for c in children]
        self.save_order(directory, order)

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

def main():
    root = tk.Tk()
    app = ContentImporterApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
