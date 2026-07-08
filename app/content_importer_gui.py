import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import shutil
import os
import sys
import json
import subprocess
from datetime import datetime

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
        self.root.geometry("700x700")  # Expanded size
        self.root.minsize(600, 600)
        self.root.configure(bg=BG_COLOR)
        
        # Bind Escape key to close
        self.root.bind("<Escape>", lambda e: self.root.destroy())
        self.style = ttk.Style()
        self.apply_dark_theme()
        
        # Custom button style for centered icons
        self.style.configure("Centered.TButton", anchor="center")
        
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
        self.user_files_root = get_user_files_path(language)
        
        # State
        self.target_folder_var = tk.StringVar(value="HighPriority")
        self.target_folder_var.trace("w", self.on_folder_change)
        
        self.status_var = tk.StringVar(value="Ready")
        self.graduate_btn = None
        self.analyzed_filenames = set()
        self._last_stats_mtime = 0
        self._last_stats_size = 0
        
        # Manifest Order Cache
        self.manifest_ranks = {} # rel_path -> index
        self.load_manifest_ranks()
        
        self.last_action = {} # For undo functionality

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
        
        # Defer data loading slightly so the window appears instantly
        self.root.after(100, self._initial_load)

        # Auto-refresh when window gains focus (to sync with Architect commits)
        # Check if we are already in a modal dialog to avoid loops? 
        # Actually, FocusIn triggers when a modal CLOSES too. 
        self.root.bind("<FocusIn>", self._on_focus_in)
        self._ignore_refresh = False
        
        # Start background polling
        self.root.after(4000, self._poll_word_stats)

    def _poll_word_stats(self):
        """Silently checks for word_stats.json updates without full UI refresh."""
        if not self.root.winfo_exists(): return
        old_mtime = getattr(self, '_last_stats_mtime', 0)
        self._load_analyzed_filenames()
        if getattr(self, '_last_stats_mtime', 0) != old_mtime:
            self._update_graduate_button_state()
        self.root.after(4000, self._poll_word_stats)

    def _initial_load(self):
        """Initial data load after UI is visible."""
        self.status_var.set("Scanning library...")
        self.root.update_idletasks()
        self._load_analyzed_filenames()
        self.refresh_file_list()
        self.status_var.set("Ready")

    def _on_focus_in(self, event):
        if event.widget == self.root and not self._ignore_refresh:
             # Use after() to avoid recursion issues if refresh triggers another FocusIn
             self.root.after(100, self.refresh_file_list)

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

    def is_content_file(self, file_path):
        """Checks if a file is a supported content type."""
        return file_path.lower().endswith(('.txt', '.md', '.html', '.htm', '.epub', '.srt', '.ass', '.vtt', '.pdf'))

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
        
        import_group = ttk.Frame(btn_frame)
        import_group.pack(side=tk.LEFT, padx=(0, 10))
        
        add_lbl = ttk.Label(import_group, text="+ Add: ", font=("Segoe UI", 9, "bold"), foreground=TEXT_COLOR)
        add_lbl.pack(side=tk.LEFT, padx=(0, 2))
        
        add_btn = ttk.Button(import_group, text="Files", command=self.add_files, width=6)
        add_btn.pack(side=tk.LEFT, padx=0)
        
        folder_btn = ttk.Button(import_group, text="Folder", command=self.add_folder, width=7)
        folder_btn.pack(side=tk.LEFT, padx=(2, 0))
        
        del_btn = ttk.Button(btn_frame, text="- Remove", command=self.remove_files, width=10)
        del_btn.pack(side=tk.LEFT, padx=(5, 0))
        
        # Right Side Action Groups (Packed Right to Left)
        reset_btn = ttk.Button(btn_frame, text="🗑️", command=self.reset_to_folder_structure, width=4, style="Centered.TButton")
        reset_btn.pack(side=tk.RIGHT, padx=(5, 0))
        self.create_tooltip(reset_btn, "Reset Library to Folder Structure\n(Deletes manual ordering and generated manifest)")

        self.undo_btn = ttk.Button(btn_frame, text="⎌", command=self.undo_last_action, state=tk.DISABLED, width=4, style="Centered.TButton")
        self.undo_btn.pack(side=tk.RIGHT, padx=(5, 0))
        self.undo_btn.tip_text = "Undo"
        self.create_tooltip(self.undo_btn, lambda: self.undo_btn.tip_text)

        # View Group (Explorer + List)
        view_group = ttk.Frame(btn_frame)
        view_group.pack(side=tk.RIGHT, padx=(5, 0))

        explorer_btn = ttk.Button(view_group, text="📂", command=self.open_data_folder, width=4, style="Centered.TButton")
        explorer_btn.pack(side=tk.LEFT)
        self.create_tooltip(explorer_btn, "Open current folder in Explorer")
        
        list_btn = ttk.Button(view_group, text="🏆", command=self.open_graduated_list, width=4, style="Centered.TButton")
        list_btn.pack(side=tk.LEFT, padx=(2, 0))
        self.create_tooltip(list_btn, "Open Graduated Words List")

        # Graduation Group (Graduate + Demote)
        grad_group = ttk.Frame(btn_frame)
        grad_group.pack(side=tk.RIGHT, padx=(5, 0))

        self.demote_btn = ttk.Button(grad_group, text="📉 Demote", command=self.demote_content, state=tk.DISABLED)
        self.demote_btn.pack(side=tk.RIGHT, padx=(2, 0))
        self.create_tooltip(self.demote_btn, "Demote Content:\n- NOW: Move to Soon\n- Soon: Move to 6+ Months\n- 6+ Months: Cannot be demoted")

        self.graduate_btn = ttk.Button(grad_group, text="🏆 Graduate", command=self.graduate_content, state=tk.DISABLED)
        self.graduate_btn.pack(side=tk.RIGHT, padx=0)
        self.create_tooltip(self.graduate_btn, "Graduate Content:\n- NOW: Graduate consumed content (Requires Analysis)\n- Soon: Move to NOW\n- 6+ Months: Move to Soon")

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
        
        # Move Buttons
        move_btn_frame = ttk.Frame(self.list_frame)
        move_btn_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=(15, 10))
        
        # Spacers to center buttons vertically with some spread
        ttk.Frame(move_btn_frame).pack(side=tk.TOP, expand=True)
        
        self.up_btn = ttk.Button(move_btn_frame, text="▴", width=3, command=self.move_selected_up)
        self.up_btn.pack(side=tk.TOP, pady=10)
        self.create_tooltip(self.up_btn, "Move selected items up")
        
        self.down_btn = ttk.Button(move_btn_frame, text="▾", width=3, command=self.move_selected_down)
        self.down_btn.pack(side=tk.TOP, pady=10)
        self.create_tooltip(self.down_btn, "Move selected items down")
        
        ttk.Frame(move_btn_frame).pack(side=tk.TOP, expand=True)

        scrollbar = ttk.Scrollbar(self.list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.config(yscrollcommand=scrollbar.set)
        
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # DnD Events
        self.tree.bind("<Button-1>", self.on_drag_start)
        self.tree.bind("<B1-Motion>", self.on_drag_motion)
        self.tree.bind("<ButtonRelease-1>", self.on_drag_stop)
        self.tree.bind("<<TreeviewSelect>>", self._update_graduate_button_state)
        
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
        self._update_graduate_button_state()
        folder_key = self.target_folder_var.get()
        self.status_var.set(f"Switched to {folder_key}")
        
        # Update order hint
        if hasattr(self, 'order_hint_label'):
            self.order_hint_label.config(text=self.order_hints.get(folder_key, ""))

    def get_manifest_path(self):
        return os.path.join(self.user_files_root, "master_manifest.json")

    def load_manifest(self):
        path = self.get_manifest_path()
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading manifest: {e}")
        return {}

    def save_manifest(self, data):
        path = self.get_manifest_path()
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving manifest: {e}")
            messagebox.showerror("Error", f"Failed to save manifest:\n{e}")

    def load_manifest_ranks(self):
        """Build a lookup map for file ranking based on the master manifest."""
        self.manifest_ranks = {}
        manifest_path = self.get_manifest_path()
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                rank = 0
                schedule = data.get("schedule", {})
                for phase in ["PHASE_1_NOW", "PHASE_2_SOON", "PHASE_3_LATER"]:
                    entries = schedule.get(phase, [])
                    for entry in entries:
                        path = entry.get("physical_path")
                        if path and path not in self.manifest_ranks:
                            self.manifest_ranks[path] = rank
                            rank += 1
            except Exception as e:
                print(f"Error loading manifest ranks: {e}")


    def _get_ordered_items_in_dir(self, directory):
        """Returns a list of items in the directory, sorted by manifest rank, then alphabetically."""
        try:
            if not os.path.isdir(directory): return []
            disk_items = os.listdir(directory)
        except Exception:
            return []
        
        # Filter disk_items (ignore system files)
        filtered_items = [f for f in disk_items if f not in ["_order.json", "master_manifest.json", "desktop.ini"]]

        def get_rank(item):
            full_path = os.path.join(directory, item)
            # Normalize path to forward slashes for manifest lookup
            rel_path = os.path.relpath(full_path, self.data_root).replace("\\", "/")
            
            # 1. Exact Match
            if rel_path in self.manifest_ranks:
                return self.manifest_ranks[rel_path]
            
            # 2. Directory Partial Match (take best rank of children)
            if os.path.isdir(full_path):
                min_rank = 999999
                pattern = rel_path + "/"
                for path, rank in self.manifest_ranks.items():
                    if path.startswith(pattern):
                        if rank < min_rank:
                            min_rank = rank
                return min_rank
            
            return 999999

        # Sort: Rank first, then Alphabetical
        filtered_items.sort(key=lambda x: (get_rank(x), x.lower()))
        return filtered_items

    def _normalize_path(self, path):
        return os.path.relpath(path, self.data_root).replace("\\", "/")

    def add_to_manifest(self, item_path, target_folder_key):
        """Adds file(s) to the manifest. If item_path is a directory, adds all files inside."""
        manifest = self.load_manifest()
        schedule = manifest.get("schedule", {})
        phase_map = {
            "HighPriority": "PHASE_1_NOW",
            "LowPriority": "PHASE_2_SOON",
            "GoalContent": "PHASE_3_LATER"
        }
        phase_key = phase_map.get(target_folder_key)
        if not phase_key: return

        if phase_key not in schedule:
            schedule[phase_key] = []

        files_to_add = []
        if os.path.isfile(item_path):
            files_to_add.append(item_path)
        else:
            for root, _, files in os.walk(item_path):
                for f in files:
                    files_to_add.append(os.path.join(root, f))

        changed = False
        for fpath in files_to_add:
            if not self.is_content_file(fpath): continue

            # Calculate physical_path relative to data_root
            rel = os.path.relpath(fpath, self.data_root).replace("\\", "/")
            
            # Check if already exists in target phase
            if any(e.get("physical_path") == rel for e in schedule[phase_key]):
                continue
                
            parts = rel.split("/")
            # parent_folder is everything between bucket and file
            hierarchy = parts[1:-1] if len(parts) > 2 else []
            buckets = ["HighPriority", "LowPriority", "GoalContent"]
            if hierarchy and hierarchy[0] in buckets:
                hierarchy = hierarchy[1:]
            parent_folder = "/".join(hierarchy)

            entry = {
                "title": os.path.basename(fpath),
                "physical_path": rel,
                "parent_folder": parent_folder,
                "origin_source": "Manual Import",
                "type": "File",
                "status": "New"
            }
            schedule[phase_key].append(entry)
            changed = True

        if changed:
            manifest["schedule"] = schedule
            self.save_manifest(manifest)

    def remove_from_manifest(self, item_path):
        """Removes an item from all manifest phase lists."""
        manifest = self.load_manifest()
        schedule = manifest.get("schedule", {})
        rel_path = self._normalize_path(item_path)
        
        changed = False
        for phase in ["PHASE_1_NOW", "PHASE_2_SOON", "PHASE_3_LATER"]:
            if phase in schedule:
                original_len = len(schedule[phase])
                schedule[phase] = [e for e in schedule[phase] if e.get("physical_path") != rel_path]
                if len(schedule[phase]) != original_len:
                    changed = True
        
        if changed:
            manifest["schedule"] = schedule
            self.save_manifest(manifest)
            self.refresh_file_list()

    def _get_manifest_indices_for_items(self, schedule_list, items, base_dir=None):
        """Returns a sorted list of manifest indices for given paths or GROUP: names."""
        indices = set()
        target_paths = set()
        target_groups = set()
        
        for p in items:
            if p.startswith("GROUP:"):
                target_groups.add(p[6:]) # Strip "GROUP:"
            else:
                # item is absolute path
                rel = os.path.relpath(p, self.data_root).replace("\\", "/")
                target_paths.add(rel)
        
        # Scan schedule
        for i, entry in enumerate(schedule_list):
            p = entry.get("physical_path")
            parent = entry.get("parent_folder", "")
            
            if p in target_paths or parent in target_groups:
                indices.add(i)
                    
        return sorted(list(indices))

    def move_manifest_items_relative(self, items, target_path, position="after"):
        """Moves items to be immediately before or after the target_path in the manifest."""
        manifest = self.load_manifest()
        schedule = manifest.get("schedule", {})
        
        target_folder = self.target_folder_var.get()
        phase_map = {
            "HighPriority": "PHASE_1_NOW",
            "LowPriority": "PHASE_2_SOON",
            "GoalContent": "PHASE_3_LATER"
        }
        phase_key = phase_map.get(target_folder)
        if not phase_key or phase_key not in schedule: return

        lst = schedule[phase_key]
        
        # Resolve indices
        indices_to_move = self._get_manifest_indices_for_items(lst, items, self.get_current_dir())
        if not indices_to_move: return
        
        # Resolve Target Index
        target_rel = self._normalize_path(target_path)
        target_indices = self._get_manifest_indices_for_items(lst, [target_path], self.get_current_dir())
        
        if not target_indices: return
        # Target could be a folder (multiple indices).
        # If "before", target the first index.
        # If "after", target the last index.
        
        if position == "before":
            eff_target_idx = target_indices[0]
        else:
            eff_target_idx = target_indices[-1]
            
        # Extract Items
        moving_items = [lst[i] for i in indices_to_move]
        
        # Remove from list (reverse to keep indices valid)
        # Note: Removing items might shift eff_target_idx!
        # We must adjust eff_target_idx for every removed item that was *before* it.
        
        shift_adj = 0
        for i in reversed(indices_to_move):
            if i < eff_target_idx:
                shift_adj += 1
            del lst[i]
            
        eff_target_idx -= shift_adj
        
        # Insert
        if position == "before":
            insert_idx = eff_target_idx
        else:
            insert_idx = eff_target_idx + 1
            
        for item in reversed(moving_items):
            lst.insert(insert_idx, item)

        manifest["schedule"] = schedule
        self.save_manifest(manifest)
        self.refresh_file_list()

    def move_items_in_manifest(self, items, direction):
        """Moves selected items (files/folders) up or down relative to other visible items in the current folder."""
        manifest = self.load_manifest()
        schedule = manifest.get("schedule", {})
        
        target_folder = self.target_folder_var.get()
        phase_map = {
            "HighPriority": "PHASE_1_NOW",
            "LowPriority": "PHASE_2_SOON",
            "GoalContent": "PHASE_3_LATER"
        }
        phase_key = phase_map.get(target_folder)
        if not phase_key or phase_key not in schedule: return

        lst = schedule[phase_key]
        indices_to_move = self._get_manifest_indices_for_items(lst, items, self.get_current_dir())
        # Nothing selected (or nothing resolved to a manifest row) -> nothing to move.
        # Without this, indices_to_move[0]/[-1] below would raise IndexError.
        if not indices_to_move:
            return
        # Identify "visible" indices (items in current bucket)
        # current_folder is the bucket name (e.g., "HighPriority")
        current_bucket = self.target_folder_var.get()
        visible_indices = []
        for i, entry in enumerate(lst):
            p = entry.get("physical_path", "")
            # Items are visible if they are in the current bucket
            if p.startswith(current_bucket + "/"):
                visible_indices.append(i)
        visible_indices.sort()
        
        if direction == "up":
            first_moving = indices_to_move[0]
            # Find the closest visible index BEFORE our block
            target_idx = -1
            for idx in reversed(visible_indices):
                if idx < first_moving:
                    target_idx = idx
                    break
            
            if target_idx != -1:
                # Group-Awareness: Only jump to the boundary if moving BETWEEN groups.
                # If moving WITHIN the same group, move by one item only.
                target_parent = lst[target_idx].get("parent_folder", "")
                moving_parent = lst[indices_to_move[0]].get("parent_folder", "")
                
                if target_parent and target_parent != moving_parent:
                    # Find the START of that target group
                    while target_idx > 0 and lst[target_idx-1].get("parent_folder") == target_parent:
                        if target_idx - 1 not in visible_indices: break # Safety
                        target_idx -= 1
                
                moving_items = [lst[i] for i in indices_to_move]
                for i in reversed(indices_to_move): del lst[i]
                for item in reversed(moving_items): lst.insert(target_idx, item)
                    
        elif direction == "down":
            last_moving = indices_to_move[-1]
            target_idx = -1
            for idx in visible_indices:
                if idx > last_moving:
                    target_idx = idx
                    break
            
            if target_idx != -1:
                # Group-Awareness: Only jump to boundary if moving BETWEEN groups
                target_parent = lst[target_idx].get("parent_folder", "")
                moving_parent = lst[indices_to_move[-1]].get("parent_folder", "") # Use last for down
                
                if target_parent and target_parent != moving_parent:
                    # Find the END of that target group
                    while target_idx < len(lst) - 1 and lst[target_idx+1].get("parent_folder") == target_parent:
                        if target_idx + 1 not in visible_indices: break
                        target_idx += 1
                
                moving_items = [lst[i] for i in indices_to_move]
                for i in reversed(indices_to_move): del lst[i]
                
                # new_insertion_point = target_idx - len(indices_to_move) + 1
                # To be simpler: insert after old target_idx
                # (which is now target_idx - len(moving) if target was after moving)
                insert_pos = target_idx - len(moving_items) + 1
                for item in reversed(moving_items):
                    lst.insert(insert_pos, item)

        manifest["schedule"] = schedule
        self.save_manifest(manifest)
        self.refresh_file_list()

    def refresh_file_list(self):
        """Populates the GUI Treeview using the manifest as the source of truth."""
        # 1. Sync untracked disk files to manifest first (quick scan)
        self._sync_disk_to_manifest()
        
        # 1b. Load analysis results for Graduate button (Optimized Cache)
        self._load_analyzed_filenames()
        
        # 2. Re-load ranks for sorting
        self.load_manifest_ranks()
        
        # 3. Store Expansion State (by group name)
        expanded_groups = set()
        def capture_expanded(parent):
            if not self.tree: return
            for child in self.tree.get_children(parent):
                if self.tree.item(child, "open"):
                    text = self.tree.item(child, "text")
                    expanded_groups.add(text)
                capture_expanded(child)
        if self.tree: capture_expanded("")

        # 4. Clear tree
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        # 5. Get manifest data for current phase
        manifest = self.load_manifest()
        schedule = manifest.get("schedule", {})
        
        target_folder = self.target_folder_var.get()
        phase_map = {
            "HighPriority": "PHASE_1_NOW",
            "LowPriority": "PHASE_2_SOON",
            "GoalContent": "PHASE_3_LATER"
        }
        phase_key = phase_map.get(target_folder)
        if not phase_key: return

        entries = schedule.get(phase_key, [])
        
        current_group_node = None
        current_group_name = None
        
        for i, entry in enumerate(entries):
            rel_path = entry.get("physical_path")
            if not rel_path: continue
            
            abs_path = os.path.join(self.data_root, rel_path)
            if not os.path.exists(abs_path):
                continue

            # Grouping Logic:
            parent = entry.get("parent_folder", "")
            
            if parent:
                # If we are not currently in the correct group node, create/switch to it
                if parent != current_group_name:
                    current_group_name = parent
                    should_open = parent in expanded_groups
                    current_group_node = self.tree.insert("", tk.END, text=parent, values=("GROUP:" + parent,), open=should_open)
                
                # Insert file into current group
                self.tree.insert(current_group_node, tk.END, text=entry.get("title", os.path.basename(rel_path)), values=(abs_path,))
            else:
                # Not in a group, break out of any current grouping
                current_group_name = None
                current_group_node = None
                # Render as single file at root
                self.tree.insert("", tk.END, text=entry.get("title", os.path.basename(rel_path)), values=(abs_path,))
                current_group_name = None
                current_group_node = None

        # Update total count
        total_items = self.get_tree_count("")
        if hasattr(self, 'count_label') and self.count_label:
            self.count_label.config(text=f"{total_items} items tracked")
        
        self._update_graduate_button_state()

    def _sync_disk_to_manifest(self):
        """Scans the 3 main data folders and ensures any untracked files are added to the manifest."""
        manifest = self.load_manifest()
        schedule = manifest.get("schedule", { "PHASE_1_NOW": [], "PHASE_2_SOON": [], "PHASE_3_LATER": [] })
        
        # Build lookup set of existing physical paths across all phases
        existing_paths = set()
        changed = False
        for p_key in ["PHASE_1_NOW", "PHASE_2_SOON", "PHASE_3_LATER"]:
            entries = schedule.get(p_key, [])
            # Prune obsolete 'Folder' types while we are here
            clean_entries = [e for e in entries if e.get("type") != "Folder"]
            if len(clean_entries) != len(entries):
                schedule[p_key] = clean_entries
                changed = True
                
            for entry in clean_entries:
                p = entry.get("physical_path")
                if p: existing_paths.add(p)
        phase_lookup = {
            "HighPriority": "PHASE_1_NOW",
            "LowPriority": "PHASE_2_SOON",
            "GoalContent": "PHASE_3_LATER"
        }
        
        for folder, p_key in phase_lookup.items():
            abs_dir = os.path.join(self.data_root, folder)
            if not os.path.exists(abs_dir): continue
            
            # Walk disk
            for root, dirs, files in os.walk(abs_dir):
                # Filter out manifest and meta files
                for item in dirs + files:
                    if item in ["master_manifest.json", "_order.json", "desktop.ini"]:
                        continue
                        
                    fpath = os.path.join(root, item)
                    rel = os.path.relpath(fpath, self.data_root).replace("\\", "/")
                    
                    if rel not in existing_paths:
                        if os.path.isdir(fpath): continue
                        if not self.is_content_file(item): continue

                        # New file found! Add to current phase
                        parts = rel.split("/")
                        # parent_folder is the hierarchy between bucket and file
                        hierarchy = parts[1:-1] if len(parts) > 2 else []
                        buckets = ["HighPriority", "LowPriority", "GoalContent"]
                        if hierarchy and hierarchy[0] in buckets:
                            hierarchy = hierarchy[1:]
                        parent_folder = "/".join(hierarchy)
                        
                        entry = {
                            "title": item,
                            "physical_path": rel,
                            "parent_folder": parent_folder,
                            "origin_source": "Disk Sync",
                            "type": "File",
                            "status": "New"
                        }
                        if p_key not in schedule: schedule[p_key] = []
                        schedule[p_key].append(entry)
                        existing_paths.add(rel)
                        changed = True
        
        if changed:
            manifest["schedule"] = schedule
            self.save_manifest(manifest)

    def get_tree_count(self, parent):
        count = 0
        for child in self.tree.get_children(parent):
            count += 1
            count += self.get_tree_count(child)
        return count

    def set_undo_action(self, action_type, label, data):
        if hasattr(self, "_temp_manifest_snapshot"):
            data["previous_manifest"] = self._temp_manifest_snapshot
            
        self.last_action = {
            "type": action_type,
            "data": data
        }
        if self.undo_btn:
            self.undo_btn.config(state=tk.NORMAL)
            self.undo_btn.tip_text = f"Undo: {label}"

    def undo_last_action(self):
        if not self.last_action:
            return
            
        action_type = self.last_action.get("type")
        data = self.last_action.get("data", {})
        count = 0
        
        try:
            if action_type == "add":
                for path in data.get("paths", []):
                    if os.path.exists(path):
                        if os.path.isdir(path): shutil.rmtree(path)
                        else: os.remove(path)
                    count += 1
                    
            elif action_type == "move":
                for move_op in data.get("moves", []):
                    src = move_op["source"]
                    dst = move_op["dest"]
                    if os.path.exists(dst):
                        os.makedirs(os.path.dirname(src), exist_ok=True)
                        shutil.move(dst, src)
                    count += 1
                    
            elif action_type == "remove":
                for rm_op in data.get("removals", []):
                    orig = rm_op["original"]
                    trash = rm_op["trash"]
                    if os.path.exists(trash):
                        os.makedirs(os.path.dirname(orig), exist_ok=True)
                        shutil.move(trash, orig)
                    count += 1
                    
            elif action_type == "graduate":
                moves = data.get("moves", [])
                words_added = data.get("words_added", 0)
                sources = data.get("sources", [])
                
                for move_op in moves:
                    src = move_op["source"]
                    dst = move_op["dest"]
                    if os.path.exists(dst):
                        os.makedirs(os.path.dirname(src), exist_ok=True)
                        shutil.move(dst, src)
                    count += 1
                
                if words_added > 0 and sources:
                    project_root = os.path.dirname(os.path.dirname(self.data_root))
                    grad_list_path = os.path.join(project_root, "User Files", self.language, "GraduatedList.txt")
                    if os.path.exists(grad_list_path):
                        with open(grad_list_path, 'r', encoding='utf-8') as f:
                            lines = f.readlines()
                            
                        for source_rel in sources:
                            target_header = f"# Source: {source_rel}"
                            header_idx = -1
                            for i in range(len(lines)-1, -1, -1):
                                if target_header in lines[i]:
                                    header_idx = i
                                    break
                                    
                            if header_idx != -1:
                                end_idx = header_idx + 1
                                for i in range(header_idx + 1, len(lines)):
                                    if lines[i].strip() == "" or lines[i].startswith("# Source:"):
                                        if not lines[i].startswith("# Source:"): end_idx = i + 1
                                        break
                                    end_idx = i + 1
                                del lines[header_idx:end_idx]
                                
                        with open(grad_list_path, 'w', encoding='utf-8') as f:
                            f.writelines(lines)
                            
            if "previous_manifest" in data:
                self.save_manifest(data["previous_manifest"])
                
        except Exception as e:
            messagebox.showerror("Undo Error", f"Failed to undo action: {e}")
            
        self.last_action = {}
        if self.undo_btn:
            self.undo_btn.config(state=tk.DISABLED)
            self.undo_btn.tip_text = "Undo"
            
        self.refresh_file_list()
        self.status_var.set(f"Undid past action ({count} items restored)")

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
            self._temp_manifest_snapshot = self.load_manifest()
            count = 0
            target_folder_key = self.target_folder_var.get()
            added_paths = []
            
            for path in filepaths:
                try:
                    filename = os.path.basename(path)
                    dest = os.path.join(target_dir, filename)
                    shutil.copy2(path, dest)
                    
                    self.add_to_manifest(dest, target_folder_key)
                    added_paths.append(dest)
                    count += 1
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to copy {filename}:\n{e}")
            
            if added_paths:
                self.set_undo_action("add", "Add Files", {"paths": added_paths})
                
            self.refresh_file_list()
            self.status_var.set(f"Added {count} files to {self.target_folder_var.get()} ({self.language})")
            messagebox.showinfo("Success", f"Successfully added {count} files.")

    def _unique_path(self, path):
        """Return a non-colliding path, appending ' (n)' before the extension if needed."""
        if not os.path.exists(path):
            return path
        base, ext = os.path.splitext(path)
        n = 2
        while os.path.exists(f"{base} ({n}){ext}"):
            n += 1
        return f"{base} ({n}){ext}"

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
            
        self._temp_manifest_snapshot = self.load_manifest()

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

            dest_existed = os.path.isdir(dest)
            if os.path.isfile(dest):
                messagebox.showerror("Error", f"A file named '{folder_name}' already exists here.")
                return
            if dest_existed:
                if not messagebox.askyesno(
                    "Merge Folder",
                    f"Folder '{folder_name}' already exists in '{self.target_folder_var.get()}'.\n"
                    "Merge new files into it? Existing files are kept — nothing is overwritten."
                ):
                    return

            # Non-destructive merge: copy supported files into dest, preserving structure.
            # Existing files are never overwritten — an identical file is skipped, and a
            # same-named file with different content is added under a de-duped name.
            import filecmp
            added_paths = []
            already = 0
            renamed = 0
            for root, _, files in os.walk(folder_path):
                rel_root = os.path.relpath(root, folder_path)
                target_root = dest if rel_root == "." else os.path.join(dest, rel_root)
                for name in sorted(files):
                    src_file = os.path.join(root, name)
                    if not self.is_content_file(src_file):
                        continue
                    os.makedirs(target_root, exist_ok=True)
                    target_file = os.path.join(target_root, name)
                    if os.path.exists(target_file):
                        if filecmp.cmp(src_file, target_file, shallow=False):
                            already += 1
                            continue  # identical file already present — skip
                        target_file = self._unique_path(target_file)
                        renamed += 1
                    shutil.copy2(src_file, target_file)
                    added_paths.append(target_file)

            if not added_paths:
                if not dest_existed and os.path.isdir(dest) and not os.listdir(dest):
                    os.rmdir(dest)  # remove the empty dir we may have just created
                messagebox.showwarning(
                    "No New Files",
                    "No new supported content files were found in the selected folder."
                    if already else
                    "No supported content files were found in the selected folder."
                )
                return

            self.add_to_manifest(dest, self.target_folder_var.get())
            # Undo removes exactly what we added: for a merge, only the new files (preserving
            # pre-existing content); for a brand-new folder, the whole folder.
            undo_paths = [dest] if not dest_existed else added_paths
            self.set_undo_action("add", "Add Folder", {"paths": undo_paths})
            
            self.refresh_file_list()
            summary = f"Added {len(added_paths)} file(s) to '{folder_name}'."
            if already:
                summary += f" {already} already present."
            if renamed:
                summary += f" {renamed} kept as a copy (name clash)."
            self.status_var.set(summary)
            messagebox.showinfo("Success", summary)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to copy folder '{folder_name}':\n{e}")

    def _resolve_items_to_paths(self, item_ids):
        """Resolves a list of tree item IDs (files or groups) into a list of absolute file paths."""
        paths = []
        for item_id in item_ids:
            vals = self.tree.item(item_id, "values")
            if not vals: continue
            
            val = str(vals[0])
            if val.startswith("GROUP:"):
                for child in self.tree.get_children(item_id):
                    child_vals = self.tree.item(child, "values")
                    if child_vals: paths.append(child_vals[0])
            else:
                paths.append(val)
        return list(set(paths)) # Unique paths

    def demote_content(self):
        selected_items = self.tree.selection()
        if not selected_items:
            messagebox.showwarning("No Selection", "Please select items to demote.")
            return

        current_folder = self.target_folder_var.get()
        destination_map = {
            "GoalContent": None,
            "LowPriority": "GoalContent",
            "HighPriority": "LowPriority"
        }
        
        dest_folder_name = destination_map.get(current_folder)
        if not dest_folder_name:
            messagebox.showinfo("Info", "Cannot demote from this folder.")
            return
            
        dest_root = os.path.join(self.data_root, dest_folder_name)
        items_to_process = self._resolve_items_to_paths(selected_items)
        if not items_to_process: return

        # Friendly mapping for dialogs
        names_map = {
            "HighPriority": "NOW",
            "LowPriority": "Soon",
            "GoalContent": "6+ months"
        }
        friendly_src = names_map.get(current_folder, current_folder)
        friendly_dest = names_map.get(dest_folder_name, dest_folder_name)

        msg = f"Demote {len(selected_items)} items from '{friendly_src}' to '{friendly_dest}'?"
        self._ignore_refresh = True
        confirm = messagebox.askyesno("Confirm Demotion", msg)
        self._ignore_refresh = False
        
        if not confirm:
            return

        # Ensure destination exists
        if not os.path.exists(dest_root):
            os.makedirs(dest_root)
            
        count = 0
        self._temp_manifest_snapshot = self.load_manifest()
        moves_list = []
        
        try:
            for filepath in items_to_process:
                if not os.path.exists(filepath): continue
                
                # Calculate relative path within source bucket to preserve hierarchy
                source_bucket_root = os.path.join(self.data_root, current_folder)
                rel_inner = os.path.relpath(filepath, source_bucket_root)
                
                parts_inner = rel_inner.replace("\\", "/").split("/")
                buckets = ["HighPriority", "LowPriority", "GoalContent"]
                if parts_inner and parts_inner[0] in buckets:
                    parts_inner = parts_inner[1:]
                clean_rel_inner = os.path.join(*parts_inner) if parts_inner else ""
                dest = os.path.join(dest_root, clean_rel_inner)
                
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                
                # Check target structure for dupes
                base = os.path.basename(dest)
                counter = 1
                name, ext = os.path.splitext(base)
                while os.path.exists(dest):
                    dest = os.path.join(os.path.dirname(dest), f"{name}_{counter}{ext}")
                    counter += 1
                    
                shutil.move(filepath, dest)
                self.remove_from_manifest(filepath)
                self.add_to_manifest(dest, dest_folder_name)
                
                moves_list.append({
                    "source": filepath,
                    "dest": dest
                })
                count += 1
                
            if moves_list:
                self.set_undo_action("graduate", "Demote Content", {
                    "moves": moves_list,
                    "words_added": 0,
                    "sources": []
                })
                
        except Exception as e:
            messagebox.showerror("Error", f"Failed to demote files: {e}")
            
        self.refresh_file_list()
        self.status_var.set(f"Demoted {count} items.")

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
        
        # Resolve Selection (handles files and groups)
        items_to_process = self._resolve_items_to_paths(selected_items)
        
        if not items_to_process: return

        # Friendly mapping for dialogs
        names_map = {
            "HighPriority": "NOW",
            "LowPriority": "Soon",
            "GoalContent": "6+ months",
            "Graduated": "Graduated"
        }
        friendly_src = names_map.get(current_folder, current_folder)
        friendly_dest = names_map.get(dest_folder_name, dest_folder_name)

        # Confirmation Logic.
        if current_folder == "HighPriority":
            msg = (f"Graduate {len(selected_items)} items to '{friendly_dest}'?\n\n"
                   "CAUTION: This will mark words as KNOWN based on the MOST RECENT analysis.\n"
                   "Words from these files found in the 'word_stats.json' report will be added to your GraduatedList.\n\n"
                   f"The files will be moved to your local '{friendly_dest}' archive.")
        else:
            msg = f"Move {len(selected_items)} items from '{friendly_src}' to '{friendly_dest}'?"
            
        self._ignore_refresh = True
        confirm = messagebox.askyesno("Confirm Graduation", msg)
        self._ignore_refresh = False
        
        if not confirm:
            return

        # Ensure destination exists
        if not os.path.exists(dest_root):
            os.makedirs(dest_root)
            
        count = 0
        words_graduated = 0
        
        # Load Stats if High Priority
        stats = {}
        settings = {}
        try:
            from app.settings_manager import load_settings
            settings = load_settings()
        except Exception as e:
            print(f"Could not load settings: {e}")
            
        if current_folder == "HighPriority":
            try:
                # data_root is data/<lang>
                project_root = os.path.dirname(os.path.dirname(self.data_root))
                stats_path = os.path.join(project_root, "results", "word_stats.json")
                if os.path.exists(stats_path):
                    with open(stats_path, 'r', encoding='utf-8') as f:
                        stats = json.load(f)
                else:
                    print(f"Warning: word_stats.json not found at {stats_path}.")
            except Exception as e:
                print(f"Error loading stats: {e}")
                
        self._temp_manifest_snapshot = self.load_manifest()

        # Process Items
        moves_list = []
        words_added_total = 0
        sources_modified = []
        
        for source_path in items_to_process:
            if not os.path.exists(source_path): continue
            
            filename = os.path.basename(source_path)
            dest_path = os.path.join(dest_root, filename)
            
            try:
                # 1. Graduate Words Logic (High Priority only)
                if current_folder == "HighPriority" and stats and settings.get("add_graduated_words", True):
                    # Find all filenames associated with this item
                    filenames_to_match = set()
                    if os.path.isfile(source_path):
                        filenames_to_match.add(filename)
                    else:
                        for root, dirs, files in os.walk(source_path):
                            for f in files:
                                filenames_to_match.add(f)
                    
                    file_words = []
                    for key, data in stats.items():
                        sources = data.get("sources", [])
                        if any(f in sources for f in filenames_to_match):
                            parts = key.split("|")
                            if len(parts) >= 1:
                                file_words.append(parts[0])
                    
                    if file_words:
                        file_words = sorted(list(set(file_words)))
                        project_root = os.path.dirname(os.path.dirname(self.data_root))
                        user_files_dir = os.path.join(project_root, "User Files", self.language)
                        if not os.path.exists(user_files_dir):
                             os.makedirs(user_files_dir)
                        
                        rel_path = os.path.relpath(source_path, self.data_root).replace("\\", "/")
                        grad_list_path = os.path.join(user_files_dir, "GraduatedList.txt")
                        with open(grad_list_path, 'a', encoding='utf-8') as f:
                            f.write(f"\n# Source: {rel_path} ({len(file_words)} words graduated)\n")
                            for w in file_words:
                                f.write(f"{w}\n")
                        words_graduated += len(file_words)
                        words_added_total += len(file_words)
                        sources_modified.append(rel_path)

                # Calculate relative path within source bucket to preserve hierarchy
                source_bucket_root = os.path.join(self.data_root, current_folder)
                rel_inner = os.path.relpath(source_path, source_bucket_root)
                
                # Sanity: prevent bucket leak in subfolders
                parts_inner = rel_inner.replace("\\", "/").split("/")
                buckets = ["HighPriority", "LowPriority", "GoalContent"]
                if parts_inner and parts_inner[0] in buckets:
                    parts_inner = parts_inner[1:]
                clean_rel_inner = os.path.join(*parts_inner) if parts_inner else ""
                dest_path = os.path.join(dest_root, clean_rel_inner)
                
                # Ensure destination directory exists
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)

                # 2. Move File
                if os.path.exists(dest_path):
                    # Simple conflict resolution: rename source
                    base, ext = os.path.splitext(os.path.basename(dest_path))
                    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                    dest_path = os.path.join(os.path.dirname(dest_path), f"{base}_{timestamp}{ext}")

                shutil.move(source_path, dest_path)
                
                # 3. Update Manifest
                self.remove_from_manifest(source_path)
                
                if dest_folder_name in ["HighPriority", "LowPriority", "GoalContent"]:
                    self.add_to_manifest(dest_path, dest_folder_name)
                
                moves_list.append({"source": source_path, "dest": dest_path})
                count += 1
                
            except Exception as e:
                messagebox.showerror("Error", f"Failed to graduate {filename}:\n{e}")
        
        self.set_undo_action("graduate", "Graduate", {"moves": moves_list, "words_added": words_added_total, "sources": list(set(sources_modified))})
        
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
            f"Are you sure you want to delete {len(selected_items)} selected items and their contents?\nThis can be undone."
        )
        
        if confirm:
            self._temp_manifest_snapshot = self.load_manifest()
            target_dir = self.get_current_dir()
            count = 0
            
            # Resolve to absolute paths robustly
            paths_to_delete = self._resolve_items_to_paths(selected_items)
            
            trash_dir = os.path.join(self.data_root, ".trash")
            os.makedirs(trash_dir, exist_ok=True)
            removals_list = []
            
            for path in paths_to_delete:
                try:
                    if os.path.exists(path):
                        # Move to trash instead of deleting
                        filename = os.path.basename(path)
                        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                        base, ext = os.path.splitext(filename)
                        trash_path = os.path.join(trash_dir, f"{base}_{timestamp}{ext}")
                        
                        shutil.move(path, trash_path)
                        removals_list.append({"original": path, "trash": trash_path})
                        
                    self.remove_from_manifest(path)
                    count += 1
                except Exception as e:
                    print(f"Error deleting {path}: {e}")
            
            # Ensure parents empty
            for path in paths_to_delete:
                 parent = os.path.dirname(path)
                 if os.path.exists(parent) and not os.listdir(parent):
                      try: os.rmdir(parent)
                      except: pass
            
            if removals_list:
                self.set_undo_action("remove", "Remove Items", {"removals": removals_list})
                
            self.refresh_file_list()
            self.status_var.set(f"Removed {count} items.")

    def _get_drop_region(self, item, y):
        """Determine if drop is above or below the target item."""
        bbox = self.tree.bbox(item)
        if not bbox: return "below"
        
        h = bbox[3]
        offset_y = y - bbox[1]
        
        return "above" if offset_y < h / 2 else "below"

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
        if not target_item:
            return

        # Simplified to just set the state for on_drag_stop.
        # _get_drop_region now only returns "above" or "below".
        self._last_drop_region = self._get_drop_region(target_item, event.y)
        self._last_drop_target = target_item

    def on_drag_stop(self, event):
        # Clean up visuals
        if hasattr(self, '_drag_highlight') and self._drag_highlight:
            self.tree.item(self._drag_highlight, tags=())
            self._drag_highlight = None
            
        target_item = self.tree.identify_row(event.y)
        if not target_item or not self._drag_item: return
        
        # Resolve what we are moving (could be multiple selected items)
        selected_ids = self.tree.selection()
        if not selected_ids: return
        
        # Determine region (above/below)
        region = self._get_drop_region(target_item, event.y)
        if target_item in selected_ids: return # Don't drop on self
        
        # Get target reference
        target_path_val = self.tree.item(target_item, "values")[0]
        
        # Get everything to move
        items_to_move = [self.tree.item(i, "values")[0] for i in selected_ids if self.tree.item(i, "values")]
        
        # Reorder manifest strictly
        pos = "before" if region == "above" else "after"
        self.move_manifest_items_relative(items_to_move, target_path_val, pos)

        self.refresh_file_list()
        self.status_var.set("Order updated.")
        
        # Restore selection
        self._restore_selection(items_to_move)

    def move_selected_up(self):
        selected = self.tree.selection()
        if not selected: return
        # Restore based on original values (supports both GROUP: and paths)
        to_restore = [self.tree.item(i, "values")[0] for i in selected if self.tree.item(i, "values")]
        
        # Resolve Selection (handles files and groups)
        items = self._resolve_items_to_paths(selected)
        if not items: return
                
        self.move_items_in_manifest(items, "up")
        self._restore_selection(to_restore)

    def move_selected_down(self):
        selected = self.tree.selection()
        if not selected: return
        # Restore based on original values 
        to_restore = [self.tree.item(i, "values")[0] for i in selected if self.tree.item(i, "values")]

        # Resolve Selection (handles files and groups)
        items = self._resolve_items_to_paths(selected)
        if not items: return
                
        self.move_items_in_manifest(items, "down")
        self._restore_selection(to_restore)
    
    def _restore_selection(self, paths):
        # Scan tree for these paths
        to_select = []
        for item in self.tree.get_children(""): # Only top level? No, recursive.
            # Tree traversal needed
            pass # Too complex to implement perfectly right now, user can reselect.
        # Simple implementation:
        def find_nodes(parent):
            nodes = []
            for child in self.tree.get_children(parent):
                vals = self.tree.item(child, "values")
                if vals and vals[0] in paths:
                    nodes.append(child)
                nodes.extend(find_nodes(child))
            return nodes
        
        nodes = find_nodes("")
        if nodes:
            self.tree.selection_set(nodes)
            self.tree.see(nodes[0])


    def reset_to_folder_structure(self):
        """Regenerates the master manifest based on the physical folder structure."""
        msg = ("This will reset your library order to match the physical folders.\n\n"
               "It will REGENERATE your manifest based on the files on disk.\n"
               "This ensures all files are tracked and reordering works correctly.\n\n"
               "Proceed?")
        if not messagebox.askyesno("Confirm Reset", msg):
            return
            
        try:
            # KEEP SNAPSHOT FOR UNDO
            snapshot = self.load_manifest()
            
            # 1. Clear existing manifest schedule but keep metadata
            manifest = self.load_manifest()
            manifest["schedule"] = {
                "PHASE_1_NOW": [],
                "PHASE_2_SOON": [],
                "PHASE_3_LATER": []
            }
            
            # 2. Re-scan all folders
            phase_map = {
                "HighPriority": "PHASE_1_NOW",
                "LowPriority": "PHASE_2_SOON",
                "GoalContent": "PHASE_3_LATER"
            }
            
            for folder, p_key in phase_map.items():
                abs_dir = os.path.join(self.data_root, folder)
                if not os.path.exists(abs_dir): continue
                
                # Alphabetical sort, relying purely on manifest for order
                def get_ordered_level(directory):
                    items = os.listdir(directory)
                    # Filter system/legacy files
                    items = [i for i in items if i not in ["_order.json", "master_manifest.json", "desktop.ini"]]
                    items.sort(key=lambda x: x.lower())
                    return items

                def walk_and_add(directory):
                    items = get_ordered_level(directory)
                    for item in items:
                        fpath = os.path.join(directory, item)
                        rel = os.path.relpath(fpath, self.data_root).replace("\\", "/")
                        
                        if os.path.isdir(fpath):
                            walk_and_add(fpath)
                            continue
                            
                        if not self.is_content_file(item): continue
                        
                        parts = rel.split("/")
                        # parent_folder is the hierarchy between bucket and file
                        hierarchy = parts[1:-1] if len(parts) > 2 else []
                        buckets = ["HighPriority", "LowPriority", "GoalContent"]
                        if hierarchy and hierarchy[0] in buckets:
                            hierarchy = hierarchy[1:]
                        parent_folder = "/".join(hierarchy)
                        
                        # Add to manifest
                        entry = {
                            "title": item,
                            "physical_path": rel,
                            "parent_folder": parent_folder,
                            "origin_source": "Reset",
                            "type": "File",
                            "status": "New"
                        }
                        manifest["schedule"][p_key].append(entry)

                walk_and_add(abs_dir)

            # 3. Save, Set Undo, and Refresh
            self.save_manifest(manifest)
            self._temp_manifest_snapshot = snapshot 
            self.set_undo_action("reset", "Reset Library", {})
            self.refresh_file_list()
            messagebox.showinfo("Success", "Library manifest regenerated from disk.")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to reset library: {e}")

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

    def _load_analyzed_filenames(self):
        """Loads the set of filenames that have been analyzed from word_stats.json (Smart Caching)."""
        try:
            # project_root is two levels up from data/<lang>
            project_root = os.path.dirname(os.path.dirname(self.data_root))
            stats_path = os.path.join(project_root, "results", "word_stats.json")
            
            if not os.path.exists(stats_path):
                self.analyzed_filenames = set()
                self._last_stats_mtime = 0
                self._last_stats_size = 0
                return

            # Smart caching: check mtime and size before parsing
            current_mtime = os.path.getmtime(stats_path)
            current_size = os.path.getsize(stats_path)
            
            if current_mtime == self._last_stats_mtime and current_size == self._last_stats_size:
                return # No changes, skip reload

            with open(stats_path, 'r', encoding='utf-8') as f:
                stats = json.load(f)
            
            new_analyzed = set()
            for data in stats.values():
                sources = data.get("sources", [])
                for s in sources:
                    new_analyzed.add(s)
            
            self.analyzed_filenames = new_analyzed
            self._last_stats_mtime = current_mtime
            self._last_stats_size = current_size
            
        except Exception as e:
            print(f"Error loading analyzed filenames cache: {e}")

    def _update_graduate_button_state(self, event=None):
        """Enable buttons only if selection is valid."""
        selected_items = self.tree.selection()
        
        demote_active = bool(selected_items and self.target_folder_var.get() != "GoalContent")
        
        if hasattr(self, 'demote_btn') and self.demote_btn:
            self.demote_btn.config(state=tk.NORMAL if demote_active else tk.DISABLED)
            
        if not self.graduate_btn:
            return
            
        if not selected_items:
            self.graduate_btn.config(state=tk.DISABLED)
            return

        current_folder = self.target_folder_var.get()
        if current_folder != "HighPriority":
            self.graduate_btn.config(state=tk.NORMAL)
            return

        if self._has_analysis_for_selection(selected_items):
            self.graduate_btn.config(state=tk.NORMAL)
        else:
            self.graduate_btn.config(state=tk.DISABLED)

    def _has_analysis_for_selection(self, selected_items):
        """Checks if there's any vocabulary data cached for the selected items (Optimized)."""
        items_to_process = self._resolve_items_to_paths(selected_items)
        if not items_to_process:
            return False

        if not self.analyzed_filenames:
            return False

        # Build a set of filenames to match
        filenames_to_check = set()
        for source_path in items_to_process:
            if os.path.isfile(source_path):
                filenames_to_check.add(os.path.basename(source_path))
            else:
                for root, _, files in os.walk(source_path):
                    for f in files:
                        filenames_to_check.add(f)

        # Fast set intersection check
        return not filenames_to_check.isdisjoint(self.analyzed_filenames)

    def create_tooltip(self, widget, text_or_callable):
        def show_tip(event):
            tip = tk.Toplevel()
            tip.wm_overrideredirect(True)
            tip.wm_geometry(f"+{event.x_root+15}+{event.y_root+15}")
            tip.configure(bg=SURFACE_COLOR)
            
            display_text = text_or_callable() if callable(text_or_callable) else text_or_callable
            
            label = tk.Label(tip, text=display_text, bg=SURFACE_COLOR, fg=TEXT_COLOR, 
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
