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
        self.root.geometry("770x787")  # +10% width, -10% height vs the previous 700x875
        self.root.minsize(660, 675)
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
        self._last_stats_source = None   # which file _load_analyzed_filenames last read (sidecar vs word_stats)

        # Manifest Order Cache
        self.manifest_ranks = {} # rel_path -> index
        self.load_manifest_ranks()

        # Per-tier tree freshness: tier -> manifest mtime the tree was last built at. A tab switch
        # rebuilds ~hundreds of Treeview rows, which is the visible lag on a big library; when the
        # manifest hasn't changed since a tier's tree was built, we skip the rebuild entirely.
        self._tier_built_sig = {}
        
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
        """Initial data load. Paint the static chrome (tabs, tier hints, empty tree) FIRST via
        update_idletasks, then load the library data.

        Note: on a large library this whole load is now <200 ms — the old multi-second freeze was
        entirely the word_stats.json parse in _load_analyzed_filenames, now served by the tiny
        analyzed_files.json sidecar (~9 ms). Measured: disk walk 25 ms, per-tier Treeview inserts
        sub-100 ms. So the data load stays on the main thread (a worker + chunked inserts would add
        risk for no measurable gain). See docs/Sidecar_Performance_Spec.md."""
        # Populate the tier description + "order matters" hint and force a FULL render (window map +
        # paint) BEFORE the data load, so that text appears with zero latency even while the file list
        # is still populating. update_idletasks() alone doesn't paint the initial window map, so the
        # chrome otherwise appeared together with the library; root.update() renders it immediately.
        self._sync_tier_meta()
        self.status_var.set("Loading library…")
        self.root.update()
        self._load_analyzed_filenames()
        self.refresh_file_list()
        self.status_var.set("Ready")

    def _on_focus_in(self, event):
        if event.widget == self.root and not self._ignore_refresh:
             # Use after() to avoid recursion issues if refresh triggers another FocusIn. force=True:
             # returning focus should re-scan disk for out-of-band changes (a delete/edit that doesn't
             # move the manifest mtime), not take the tab-switch fast path.
             self.root.after(100, lambda: self.refresh_file_list(force=True))

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

        # Segmented "tab" look for the tier selector (Radiobuttons styled as buttons): the active
        # tier fills with the accent colour, like a selected tab.
        self.style.configure("Tier.Toolbutton",
            background=SURFACE_COLOR, foreground=TEXT_COLOR, borderwidth=0,
            padding=(16, 7), font=("Segoe UI", 10, "bold")
        )
        self.style.map("Tier.Toolbutton",
            background=[('selected', ACCENT_COLOR), ('active', "#3a3a3a")],
            foreground=[('selected', BG_COLOR)]
        )

        # Prominent "big option" button — matches the main GUI's Action.TButton so the Add Content
        # choices read as large, full-width options the user can confidently click.
        # Taller so the Add Content options feel like big, central choices.
        self.style.configure("Action.TButton", padding=(10, 14), font=("Segoe UI", 10, "bold"))
        # Same HEIGHT and FONT as Action (identical vertical padding + size-10 bold, so the glyph and
        # box line up with the Add-files button) — but as narrow as possible, for the appended icon.
        self.style.configure("ActionIcon.TButton", padding=(1, 14), font=("Segoe UI", 10, "bold"), anchor="center")
        # ▲▼ reorder arrows: keep the small icon (font 9) but a larger clickable button (padding).
        self.style.configure("Move.TButton", padding=(8, 6), font=("Segoe UI", 9), anchor="center")

        # Red ▶ YouTube button — same prominent size as the other Add Content options.
        self.style.configure("Youtube.TButton", padding=(10, 14),
            font=("Segoe UI", 10, "bold"), foreground=ERROR_COLOR)
        self.style.map("Youtube.TButton",
            background=[('active', ACCENT_COLOR), ('pressed', ACCENT_COLOR)],
            foreground=[('active', BG_COLOR), ('pressed', BG_COLOR)])

        # Tier tabs (ttk.Notebook): dark strip, readable text, accent fill on the active tab so ONLY
        # the colour differentiates it. Compact padding so tabs stay small; the labels are padded to a
        # common width (see setup_ui) so all three read as the same size. Fixed size in every state
        # (expand=0 on select) so a tab never grows/jumps when picked.
        # tabmargins left = 0 so the first tab sits flush with the library box's content edge.
        self.style.configure("TNotebook", background=BG_COLOR, borderwidth=0, tabmargins=(0, 4, 2, 0))
        self.style.configure("TNotebook.Tab",
            background=SURFACE_COLOR, foreground=TEXT_COLOR,
            padding=(6, 5), font=("Segoe UI", 10, "bold"), borderwidth=0)
        self.style.map("TNotebook.Tab",
            background=[("selected", ACCENT_COLOR), ("active", "#3a3a3a")],
            foreground=[("selected", BG_COLOR), ("active", TEXT_COLOR)],
            padding=[("selected", [6, 5])])
        # Drop the dotted focus ring drawn on the selected tab's label (visually noisy). Redefining the
        # tab layout WITHOUT the Notebook.focus element removes it while keeping padding + label.
        self.style.layout("TNotebook.Tab", [
            ("Notebook.tab", {"sticky": "nswe", "children": [
                ("Notebook.padding", {"side": "top", "sticky": "nswe", "children": [
                    ("Notebook.label", {"side": "top", "sticky": ""})]})]})])   # clam grows the selected tab's padding ('6 4 6 2') — pin it

        # File-list Treeview (kept here so a single apply_dark_theme() fully restores our look — the
        # in-process YouTube window switches the global ttk theme and we re-assert on focus return).
        self.style.configure("Treeview",
            background=SURFACE_COLOR, foreground=TEXT_COLOR, fieldbackground=SURFACE_COLOR,
            borderwidth=0, font=("Segoe UI", 10))
        self.style.map("Treeview",
            background=[('selected', ACCENT_COLOR)], foreground=[('selected', BG_COLOR)])

        # File-list scrollbar: dark to match the theme (clam's default renders it light/white).
        self.style.configure("Vertical.TScrollbar",
            background=SURFACE_COLOR, troughcolor=BG_COLOR, bordercolor=BG_COLOR,
            arrowcolor=TEXT_COLOR, darkcolor=SURFACE_COLOR, lightcolor=SURFACE_COLOR)
        self.style.map("Vertical.TScrollbar",
            background=[("active", ACCENT_COLOR), ("pressed", ACCENT_COLOR)])

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

        # --- ADD CONTENT (options row) ---
        # The primary ways to get content in. These target the section selected below (Phase 3 will
        # replace the radios with tabs and this row will sit above them). YouTube is added in Phase 5.
        # Shorter box (~75% of before) — the "Also" line moved out (below), and the buttons are taller
        # so they fill it and feel like big central choices.
        options_frame = ttk.LabelFrame(main_frame, text=" Add Content ", padding=(12, 10))
        options_frame.pack(fill=tk.X, pady=(0, 4))

        add_row = ttk.Frame(options_frame)
        add_row.pack(fill=tk.X)

        # Three EQUAL-width option groups (like the main GUI): [Add files + 📂] · Extract · YouTube.
        # The folder icon lives INSIDE the Add-files group as its small tail, so the pair matches the
        # width of the Extract / YouTube buttons instead of overrunning them.
        addfiles_group = ttk.Frame(add_row)
        addfiles_group.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 6))
        add_files_btn = ttk.Button(addfiles_group, text="📁 Add files", command=self.add_files, style="Action.TButton")
        add_files_btn.pack(side=tk.LEFT, expand=True, fill=tk.X)
        self.create_tooltip(add_files_btn,
                            "Add ready text/subtitle files to the selected section.\n"
                            "Formats: TXT, MD, SRT, ASS. (EPUB / Anki decks -> use Extract.)")
        folder_icon_btn = ttk.Button(addfiles_group, text="📂", command=self.add_folder, style="ActionIcon.TButton")
        folder_icon_btn.pack(side=tk.LEFT, padx=(2, 0))    # the tail end of the Add-files button
        self.create_tooltip(folder_icon_btn, "Add a whole folder (non-destructive merge).")

        extract_btn = ttk.Button(add_row, text="📖 Extract (EPUB / Anki)", command=self.open_splicer, style="Action.TButton")
        extract_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 6))
        self.create_tooltip(extract_btn, "Extract & split an EPUB or Anki deck into text (also added to the selected section).")

        # ▶ YouTube — shown only when the transcript downloader is opted-in AND the optional module is
        # present (mirrors main.py's update_youtube_visibility gate). Downloads land in Processed and
        # get copied into the active section (see _on_youtube_downloaded).
        self.btn_youtube = None
        if self._youtube_enabled():
            self.btn_youtube = ttk.Button(add_row, text="▶ YouTube", command=self.open_youtube, style="Youtube.TButton")
            self.btn_youtube.pack(side=tk.LEFT, expand=True, fill=tk.X)
            self.create_tooltip(self.btn_youtube, "Download YouTube transcripts into the selected section.")

        # Below the box, right-justified: the muted quick-links, then a '?' help memo to their right.
        helper_row = ttk.Frame(main_frame)
        helper_row.pack(fill=tk.X, pady=(0, 12))
        helper_inner = ttk.Frame(helper_row)
        helper_inner.pack(side=tk.RIGHT)      # hug the right edge
        ttk.Label(helper_inner, text="Also:", foreground="#888").pack(side=tk.LEFT)
        paste_lbl = ttk.Label(helper_inner, text="Paste text", foreground=ACCENT_COLOR, cursor="hand2")
        paste_lbl.pack(side=tk.LEFT, padx=(6, 0))
        paste_lbl.bind("<Button-1>", lambda e: self.paste_text_dialog())
        if self._subtitle_url():   # only shown when the active language has a known source (JA)
            ttk.Label(helper_inner, text="·", foreground="#555").pack(side=tk.LEFT, padx=6)
            sub_lbl = ttk.Label(helper_inner, text="Anime subtitles ↗", foreground=ACCENT_COLOR, cursor="hand2")
            sub_lbl.pack(side=tk.LEFT)
            sub_lbl.bind("<Button-1>", lambda e: self.open_subtitle_site())
        help_icon = tk.Label(helper_inner, text="?", font=("Segoe UI", 10, "bold"),
                             bg=SURFACE_COLOR, fg=ACCENT_COLOR, cursor="hand2", padx=6, pady=2, relief="flat")
        help_icon.pack(side=tk.LEFT, padx=(10, 0))   # to the right of the links
        self.create_tooltip(help_icon, "Your vocab journey will prioritize words based on your immersion "
                                       "content, and how soon you'll see them")

        # Refresh the library when focus returns after a launched tool (splicer) closes.
        self._refresh_on_focus = False
        self.root.bind("<FocusIn>", self._on_focus_in)

        # Tier metadata — (tab label, description) + the "order matters" hint. Used by the tabs below
        # and the add/paste flows. The tier is still tracked by self.target_folder_var (now driven by
        # the tabs instead of the old radio list).
        self.folder_map = {
            "HighPriority": ("NOW", "Content you're consuming right now (next ~2 weeks)."),
            "LowPriority": ("Soon", "Within the next 6 months."),
            "GoalContent": ("6+ months", "Aspirations or \"someday\" books.")
        }
        # (prefix, emphasis, suffix) — only the emphasis segment is underlined in the tab-strip hint.
        self.order_hints = {
            "HighPriority": ("Order matters ", "a lot", "!"),
            "LowPriority": ("Order matters ", "a little", "."),
            "GoalContent": ("Order ", "doesn't", " matter.")
        }

        # --- LIBRARY: toolbar above the tabs, then real connected tabs (one file-list per tier) ---
        step2_frame = ttk.LabelFrame(main_frame, text=" Your Library ", padding="15")
        step2_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))

        # The whole manage area lives in library_body; when the library is empty we hide it and show
        # the onboarding card instead (see _update_empty_state).
        self.library_body = ttk.Frame(step2_frame)
        self.library_body.pack(fill=tk.BOTH, expand=True)
        self.empty_card = self._build_empty_card(step2_frame)

        # --- Manage toolbar (ABOVE the tabs), single line: the tier DESCRIPTION on the left, all the
        #     action buttons clustered on the right. Remove is icon-only; Demote/Graduate keep a label
        #     (less obvious); the utility actions stay icon-only. (Buttons packed right-to-left so they
        #     read left→right as: Remove · Demote · Graduate  ·  📂 🎓 ⎌ 🗑.)
        toolbar = ttk.Frame(self.library_body)
        toolbar.pack(fill=tk.X, pady=(0, 8))

        self.tier_desc_var = tk.StringVar()
        self.tier_desc_lbl = ttk.Label(toolbar, textvariable=self.tier_desc_var, foreground=ACCENT_COLOR,
                                       font=("Segoe UI", 9, "italic"))
        self.tier_desc_lbl.pack(side=tk.LEFT)   # description, left-justified on the same line

        reset_btn = ttk.Button(toolbar, text="\U0001f5d1️", command=self.reset_to_folder_structure, width=4, style="Centered.TButton")
        reset_btn.pack(side=tk.RIGHT, padx=(4, 0))
        self.create_tooltip(reset_btn, "Reset Library to Folder Structure\n(Deletes manual ordering and generated manifest)")
        self.undo_btn = ttk.Button(toolbar, text="⎌", command=self.undo_last_action, state=tk.DISABLED, width=4, style="Centered.TButton")
        self.undo_btn.pack(side=tk.RIGHT, padx=(4, 0))
        self.undo_btn.tip_text = "Undo"
        self.create_tooltip(self.undo_btn, lambda: self.undo_btn.tip_text)
        gradlist_btn = ttk.Button(toolbar, text="\U0001f393", command=self.open_graduated_list, width=4, style="Centered.TButton")
        gradlist_btn.pack(side=tk.RIGHT, padx=(4, 0))
        self.create_tooltip(gradlist_btn, "Open Graduated Words List")
        explorer_btn = ttk.Button(toolbar, text="\U0001f4c2", command=self.open_data_folder, width=4, style="Centered.TButton")
        explorer_btn.pack(side=tk.RIGHT, padx=(10, 0))   # gap between the text actions and the icons
        self.create_tooltip(explorer_btn, "Open current folder in Explorer")
        self.graduate_btn = ttk.Button(toolbar, text="\U0001f3c6 Graduate", command=self.graduate_content, state=tk.DISABLED)
        self.graduate_btn.pack(side=tk.RIGHT, padx=(4, 0))
        self.create_tooltip(self.graduate_btn, "Graduate Content:\n- NOW: Graduate consumed content (Requires Analysis)\n- Soon: Move to NOW\n- 6+ Months: Move to Soon")
        self.demote_btn = ttk.Button(toolbar, text="\U0001f4c9 Demote", command=self.demote_content, state=tk.DISABLED)
        self.demote_btn.pack(side=tk.RIGHT, padx=(4, 0))
        self.create_tooltip(self.demote_btn, "Demote Content:\n- NOW: Move to Soon\n- Soon: Move to 6+ Months\n- 6+ Months: Cannot be demoted")
        del_btn = ttk.Button(toolbar, text="➖", command=self.remove_files, width=4, style="Centered.TButton")
        del_btn.pack(side=tk.RIGHT, padx=(4, 0))
        self.create_tooltip(del_btn, "Remove the selected items from this section.")

        # --- Tabs (one file-list per tier) with the ▲▼ reorder arrows on the RIGHT side of the list.
        #     self.tree always points at the ACTIVE tab's tree, so every file/reorder handler (all
        #     keyed on self.tree) is unchanged.
        nb_row = ttk.Frame(self.library_body)
        nb_row.pack(fill=tk.BOTH, expand=True)

        self.notebook = ttk.Notebook(nb_row)
        self.notebook.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Pad tab labels to a common PIXEL width so all three tabs are the same size (only the accent
        # colour marks the active one). ttk.Notebook has no per-tab width option, so we equalize by
        # padding the shorter labels with spaces measured in the tab font.
        import tkinter.font as tkfont
        tab_font = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        _labels = [lbl for (lbl, _sub) in self.folder_map.values()]
        _space_px = tab_font.measure(" ") or 4
        _target_px = max(tab_font.measure(l) for l in _labels)  # tight: hug the longest label
        def _tab_text(lbl):
            spaces = max(0, round((_target_px - tab_font.measure(lbl)) / _space_px))
            left = spaces // 2
            return " " * left + lbl + " " * (spaces - left)

        self.tier_trees = {}
        self._tab_tiers = []          # tab index -> tier key
        for key, (label, _sub) in self.folder_map.items():
            tab = ttk.Frame(self.notebook)
            self.tier_trees[key] = self._make_tier_tree(tab)
            self.notebook.add(tab, text=_tab_text(label))
            self._tab_tiers.append(key)
        self.tree = self.tier_trees.get(self.target_folder_var.get()) or next(iter(self.tier_trees.values()))
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        # The "order matters" hint sits inline just to the RIGHT of the tabs. Only the emphasis word
        # ('a lot' / 'a little' / 'doesn't') is underlined, so it's built from 3 tk.Labels (a single
        # label can't underline part of its text). The x is estimated from the tab font (ttk gives no
        # tab geometry pre-render): equal-width tabs ≈ _target_px + padding each.
        self.tier_meta_var = tk.StringVar()          # full text kept for logic/tests
        meta_frame = tk.Frame(nb_row, bg=BG_COLOR)
        _mf = ("Segoe UI", 9, "bold italic")
        self._meta_pre = tk.Label(meta_frame, font=_mf, bg=BG_COLOR, fg=ACCENT_COLOR, bd=0, padx=0, pady=0)
        self._meta_mid = tk.Label(meta_frame, font=("Segoe UI", 9, "bold italic underline"),
                                  bg=BG_COLOR, fg=ACCENT_COLOR, bd=0, padx=0, pady=0)
        self._meta_suf = tk.Label(meta_frame, font=_mf, bg=BG_COLOR, fg=ACCENT_COLOR, bd=0, padx=0, pady=0)
        self._meta_pre.pack(side=tk.LEFT)
        self._meta_mid.pack(side=tk.LEFT)
        self._meta_suf.pack(side=tk.LEFT)
        self.tier_meta_lbl = meta_frame              # keep the attribute name (placement / tests)
        _tab_w = _target_px + 15                                   # padded label + ~12 padding + border
        _after_tabs = int((len(self._tab_tiers) + 0.5) * _tab_w) + 4    # a touch left of before
        meta_frame.place(in_=self.notebook, x=_after_tabs, y=15, anchor="w")

        # ▲▼ reorder arrows: large and close together as a centred pair (equal space above/below via
        # the expanding spacers, so they sit off the top/bottom edges).
        move_col = ttk.Frame(nb_row)
        # 15px to the list on the left; 0 here + the frame's 15px padding on the right => the arrow
        # column sits an equal 15px from the file list and from the "Your Library" box edge.
        move_col.pack(side=tk.RIGHT, fill=tk.Y, padx=(15, 0))
        ttk.Frame(move_col).pack(expand=True)      # top spacer
        self.up_btn = ttk.Button(move_col, text="▲", width=3, command=self.move_selected_up, style="Move.TButton")
        self.up_btn.pack()
        self.create_tooltip(self.up_btn, "Move selected items up")
        self.down_btn = ttk.Button(move_col, text="▼", width=3, command=self.move_selected_down, style="Move.TButton")
        self.down_btn.pack(pady=(46, 0))           # ~2 button-heights of separation
        self.create_tooltip(self.down_btn, "Move selected items down")
        ttk.Frame(move_col).pack(expand=True)      # bottom spacer

        # --- Footer: drag hint (left) + file count (right).
        footer = ttk.Frame(self.library_body)
        footer.pack(fill=tk.X, pady=(5, 0))
        ttk.Label(footer, text="Drag and move your files in the order you will immerse",
                  foreground="#aaa", font=("Segoe UI", 9, "italic")).pack(side=tk.LEFT)
        self.count_label = ttk.Label(footer, text="0 files found", foreground="#888")
        self.count_label.pack(side=tk.RIGHT)
        self._sync_tier_meta()

        status_bar = ttk.Label(main_frame, textvariable=self.status_var, foreground="#888")
        status_bar.pack(side=tk.LEFT, pady=(15, 0))

    def get_current_dir(self):
        folder_name = self.target_folder_var.get()
        return os.path.join(self.data_root, folder_name)

    def on_folder_change(self, *args):
        self.refresh_file_list()
        self._update_graduate_button_state()
        folder_key = self.target_folder_var.get()
        self.status_var.set(f"Switched to {self.folder_map.get(folder_key, (folder_key,))[0]}")

        # Update the right-justified tier guidance (description + "order matters" hint).
        if hasattr(self, 'tier_meta_var'):
            self._sync_tier_meta()

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

    def refresh_file_list(self, force=False):
        """Populates the GUI Treeview using the manifest as the source of truth.

        On a big library the expensive part is inserting hundreds of rows. Each tier has its own
        persistent tree, so when switching to a tier whose tree already reflects the current manifest
        (unchanged mtime since it was built) we skip the rebuild and just refresh the light bits —
        making tab switches instant. force=True (focus-in, external tools) always rebuilds so an
        out-of-band change is picked up."""
        if not hasattr(self, "_tier_built_sig"):
            self._tier_built_sig = {}   # defensive: some tests construct the app without full __init__

        # 1. Sync untracked disk files to manifest first (quick scan) — may bump the manifest mtime.
        self._sync_disk_to_manifest()

        # 1b. Load analysis results for Graduate button (Optimized Cache)
        self._load_analyzed_filenames()

        target_folder = self.target_folder_var.get()
        phase_map = {
            "HighPriority": "PHASE_1_NOW",
            "LowPriority": "PHASE_2_SOON",
            "GoalContent": "PHASE_3_LATER"
        }
        phase_key = phase_map.get(target_folder)
        if not phase_key: return

        try:
            msig = os.path.getmtime(self.get_manifest_path())
        except OSError:
            msig = None

        # Fast path: this tier's tree is already current -> skip the row rebuild.
        if (not force and msig is not None and self.tree is not None
                and self._tier_built_sig.get(target_folder) == msig):
            total_items = self.get_tree_count("")
            if hasattr(self, 'count_label') and self.count_label:
                self.count_label.config(text=f"{total_items} items tracked")
            self._update_graduate_button_state()
            self._update_empty_state()
            return

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

        # Stamp this tier's tree as built at the current manifest mtime (skip its rebuild next time).
        self._tier_built_sig[target_folder] = msig

        # Update total count
        total_items = self.get_tree_count("")
        if hasattr(self, 'count_label') and self.count_label:
            self.count_label.config(text=f"{total_items} items tracked")

        self._update_graduate_button_state()
        self._update_empty_state()   # show the onboarding card iff the library has no content

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

    # --- Tier tabs (ttk.Notebook) helpers -------------------------------------------------------- #
    def _make_tier_tree(self, parent):
        """Build a file-list Treeview (+ scrollbar + the drag/select bindings) inside a tab pane."""
        holder = ttk.Frame(parent)
        holder.pack(fill=tk.BOTH, expand=True)
        tree = ttk.Treeview(holder, columns=("full_path",), show="tree", selectmode="extended")
        sb = ttk.Scrollbar(holder, orient=tk.VERTICAL, command=tree.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        tree.config(yscrollcommand=sb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree.bind("<Button-1>", self.on_drag_start)
        tree.bind("<B1-Motion>", self.on_drag_motion)
        tree.bind("<ButtonRelease-1>", self.on_drag_stop)
        tree.bind("<<TreeviewSelect>>", self._update_graduate_button_state)
        return tree

    def _on_tab_changed(self, event=None):
        """A tab was selected: point self.tree at that tier's tree, then set the shared tier var
        (its trace runs on_folder_change -> refresh_file_list + meta). Nothing else sets that var,
        so there's no feedback loop."""
        try:
            idx = self.notebook.index(self.notebook.select())
        except Exception:
            return
        tier = self._tab_tiers[idx] if 0 <= idx < len(self._tab_tiers) else "HighPriority"
        self.tree = self.tier_trees[tier]
        self.target_folder_var.set(tier)

    def _sync_tier_meta(self):
        """Split guidance for the active tier: the description shows above the toolbar; the 'order
        matters' hint shows inline on the tab strip (only its emphasis word underlined)."""
        key = self.target_folder_var.get()
        self.tier_desc_var.set(self.folder_map.get(key, ("", ""))[1])
        pre, mid, suf = self.order_hints.get(key, ("", "", ""))
        self._meta_pre.config(text=pre)
        self._meta_mid.config(text=mid)
        self._meta_suf.config(text=suf)
        self.tier_meta_var.set(f"{pre}{mid}{suf}")

    # --- Empty-state onboarding ------------------------------------------------------------------ #
    def _build_empty_card(self, parent):
        """A centered onboarding card shown INSTEAD of the tabs when the library has no content."""
        card = ttk.Frame(parent)
        inner = ttk.Frame(card)
        inner.place(relx=0.5, rely=0.45, anchor="center")
        ttk.Label(inner, text="Your library is empty", font=("Segoe UI", 14, "bold")).pack(pady=(0, 6))
        ttk.Label(inner, text="Add content using the options above.", foreground="#aaa").pack()
        ttk.Label(inner, text="— or —", foreground="#666").pack(pady=8)
        ttk.Button(inner, text="Test with samples", command=self._seed_samples_clicked,
                   style="Action.TButton").pack()
        ttk.Label(inner, text="(copies a few sample files so you can try a Journey right away)",
                  foreground="#666", font=("Segoe UI", 8, "italic")).pack(pady=(6, 0))
        return card

    def _library_is_empty(self):
        """True when NO content files exist across the three tiers (Processed/Graduated don't count)."""
        for tier in ("HighPriority", "LowPriority", "GoalContent"):
            d = os.path.join(self.data_root, tier)
            if os.path.isdir(d):
                for _root, _dirs, files in os.walk(d):
                    if any(self.is_content_file(f) for f in files):
                        return False
        return True

    def _update_empty_state(self):
        """Show the onboarding card when the library is empty, the tabbed library otherwise."""
        if not hasattr(self, "empty_card"):
            return
        if self._library_is_empty():
            self.library_body.pack_forget()
            if not self.empty_card.winfo_ismapped():
                self.empty_card.pack(fill=tk.BOTH, expand=True)
        else:
            self.empty_card.pack_forget()
            if not self.library_body.winfo_ismapped():
                self.library_body.pack(fill=tk.BOTH, expand=True)

    def _seed_samples_clicked(self):
        """'Test with samples': copy the bundled samples in, then switch to the library view."""
        from app.path_utils import seed_samples
        try:
            n = seed_samples(self.language)
        except Exception as e:
            messagebox.showerror("Error", f"Could not add samples:\n{e}")
            return
        self.status_var.set(f"Added {n} sample files")
        self.refresh_file_list()   # -> _update_empty_state reveals the tabbed library

    # --- Add Content options row: helpers -------------------------------------------------------- #
    def _subtitle_url(self):
        """Language-aware 'where to get subtitles' link. None => the link is hidden (e.g. zh has no
        known source)."""
        return {
            "ja": "https://kitsunekko.net/dirlist.php?dir=subtitles%2Fjapanese%2F",
        }.get(self.language)

    def open_subtitle_site(self):
        import webbrowser
        url = self._subtitle_url()
        if url:
            webbrowser.open(url)

    def open_splicer(self):
        """Launch the Extract/Splice tool for the selected section. It writes to Processed AND copies
        the output into that tier (--tier); the library refreshes when the tool window closes."""
        tier = self.target_folder_var.get()
        self._launch_tool("epub_importer.py", ["--language", self.language, "--tier", tier])

    def _youtube_enabled(self):
        """True when the YouTube transcript downloader is opted-in AND the optional module is present
        (same gate as main.py's update_youtube_visibility). Fails closed if either is missing."""
        try:
            from app import settings_manager
            if not settings_manager.load_settings().get("enable_youtube_transcripts", False):
                return False
            import modules.youtube_downloader  # noqa: F401 — presence check only
            return True
        except Exception:
            return False

    def open_youtube(self):
        """Open the YouTube transcript downloader in-process (host-agnostic: passes the active
        language + a callback that routes the new transcripts into the selected section)."""
        try:
            from modules.youtube_downloader import open_downloader
        except Exception as e:
            messagebox.showerror("Error", f"Could not launch YouTube Downloader:\n{e}")
            return
        # Opens in-process as a Toplevel that inherits our theme (it no longer switches the global
        # ttk theme — see app/ui_theme). New transcripts route into the active tier via on_complete.
        open_downloader(self, language=self.language, on_complete=self._on_youtube_downloaded)

    def _on_youtube_downloaded(self, created_paths):
        """After a download (into Processed), copy the new transcripts into the active section so
        they're part of the library — mirroring the splice 'Processed + tier' rule — then refresh
        (which re-registers them in the manifest via _sync_disk_to_manifest)."""
        import shutil
        tier = self.target_folder_var.get()
        tier_dir = os.path.join(self.data_root, tier)
        os.makedirs(tier_dir, exist_ok=True)
        for src in created_paths or []:
            try:
                base = os.path.basename(src.rstrip("/\\"))
                if not base:
                    continue
                dst = os.path.join(tier_dir, base)
                if os.path.isdir(src):
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                elif os.path.isfile(src) and not os.path.exists(dst):
                    shutil.copy2(src, dst)
            except Exception:
                pass
        self.status_var.set(f"Added YouTube transcripts to {self.folder_map.get(tier, (tier,))[0]}")
        self.refresh_file_list()

    def _launch_tool(self, script_name, extra_args):
        """Launch a sibling tool (the splicer) as a subprocess, frozen-vs-source aware. Flags a
        library refresh for when focus returns after the tool window closes."""
        from app.path_utils import is_frozen
        script_map = {"epub_importer.py": "epub_importer"}
        try:
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            if is_frozen():
                cmd = [sys.executable, script_map.get(script_name, script_name)] + list(extra_args)
            else:
                app_dir = os.path.dirname(os.path.abspath(__file__))
                project_root = os.path.dirname(app_dir)
                env["PYTHONPATH"] = project_root + os.pathsep + env.get("PYTHONPATH", "")
                cmd = [sys.executable, os.path.join(app_dir, script_name)] + list(extra_args)
            subprocess.Popen(cmd, env=env)
            self._refresh_on_focus = True
        except Exception as e:
            messagebox.showerror("Error", f"Could not launch {script_name}:\n{e}")

    def _on_focus_in(self, event=None):
        """Refresh the library once when focus returns after a launched tool (splicer) closes."""
        if getattr(self, "_refresh_on_focus", False):
            self._refresh_on_focus = False
            try:
                self.refresh_file_list()
            except Exception:
                pass

    def paste_text_dialog(self):
        """Paste a snippet of text and save it as a .txt into the selected section."""
        tier = self.target_folder_var.get()
        tier_label = self.folder_map.get(tier, (tier,))[0]
        dlg = tk.Toplevel(self.root)
        dlg.title("Paste text")
        dlg.configure(bg=BG_COLOR)
        dlg.geometry("520x420")
        dlg.transient(self.root)
        dlg.bind("<Escape>", lambda e: dlg.destroy())

        ttk.Label(dlg, text=f"Paste text to add to '{tier_label}':").pack(anchor=tk.W, padx=12, pady=(12, 6))
        name_row = ttk.Frame(dlg)
        name_row.pack(fill=tk.X, padx=12)
        ttk.Label(name_row, text="Name:").pack(side=tk.LEFT)
        name_var = tk.StringVar(value="Pasted text")
        ttk.Entry(name_row, textvariable=name_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))

        txt = tk.Text(dlg, height=15, wrap=tk.WORD, bg=SURFACE_COLOR, fg=TEXT_COLOR,
                      insertbackground=TEXT_COLOR, relief="flat")
        txt.pack(fill=tk.BOTH, expand=True, padx=12, pady=8)
        txt.focus_set()

        def _save():
            content = txt.get("1.0", tk.END).strip()
            if not content:
                messagebox.showwarning("Empty", "Nothing to save.", parent=dlg)
                return
            self._save_pasted_text(name_var.get().strip() or "Pasted text", content, tier)
            dlg.destroy()

        ttk.Button(dlg, text="Save", command=_save, style="Action.TButton").pack(pady=(0, 12))

    def _save_pasted_text(self, name, content, tier):
        import re
        safe = re.sub(r'[^\w\- ]+', '', name).strip().replace(" ", "_") or "Pasted_text"
        tier_dir = os.path.join(self.data_root, tier)
        os.makedirs(tier_dir, exist_ok=True)
        path = os.path.join(tier_dir, f"{safe}.txt")
        i = 1
        while os.path.exists(path):
            path = os.path.join(tier_dir, f"{safe}_{i}.txt")
            i += 1
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            messagebox.showerror("Error", f"Could not save:\n{e}")
            return
        self.status_var.set(f"Added pasted text to {self.folder_map.get(tier, (tier,))[0]}")
        self.refresh_file_list()

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
        
        # Reverse index {basename: [lemmas]} used to graduate a file's words (High Priority only).
        grad_index = {}
        settings = {}
        try:
            from app.settings_manager import load_settings
            settings = load_settings()
        except Exception as e:
            print(f"Could not load settings: {e}")

        if current_folder == "HighPriority":
            grad_index = self._load_graduate_index()
                
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
                if current_folder == "HighPriority" and grad_index and settings.get("add_graduated_words", True):
                    # Find all filenames associated with this item
                    filenames_to_match = set()
                    if os.path.isfile(source_path):
                        filenames_to_match.add(filename)
                    else:
                        for root, dirs, files in os.walk(source_path):
                            for f in files:
                                filenames_to_match.add(f)

                    # Union of every matched file's words (same result as scanning word_stats'
                    # per-word `sources`, just read from the pre-built reverse index).
                    file_words = set()
                    for f in filenames_to_match:
                        file_words.update(grad_index.get(f, []))

                    if file_words:
                        file_words = sorted(file_words)
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

    @staticmethod
    def _fresher_source(sidecar, fallback):
        """Pick which file to read: the sidecar, but only when it's at least as new as the fallback
        (word_stats.json). This ignores a stale sidecar left by an interrupted run — word_stats.json
        is always written before its sidecars, so a fresh full run makes word_stats.json newer.
        Returns the fallback path when the sidecar is absent/stale (the caller checks existence)."""
        if os.path.exists(sidecar):
            if not os.path.exists(fallback):
                return sidecar
            if os.path.getmtime(sidecar) >= os.path.getmtime(fallback):
                return sidecar
        return fallback

    def _load_graduate_index(self):
        """Return {basename: [lemmas]} for graduating a file's words.

        Prefers the `file_words.json` sidecar (~1.3 MB on the live library); falls back to building
        the reverse map from `word_stats.json` (unchanged semantics) for pre-sidecar/stale result
        folders. Returns {} when neither is available. Read on demand (only when Graduate is pressed
        on NOW), so its size never affects the responsive paths."""
        project_root = os.path.dirname(os.path.dirname(self.data_root))
        results_dir = os.path.join(project_root, "results")
        sidecar = os.path.join(results_dir, "file_words.json")
        stats_path = os.path.join(results_dir, "word_stats.json")
        source = self._fresher_source(sidecar, stats_path)
        try:
            if not os.path.exists(source):
                print(f"Warning: no analysis results found in {results_dir}.")
                return {}
            with open(source, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
            # Parse by SHAPE: the sidecar maps basename -> [lemmas] (values are lists); word_stats
            # maps word -> {"sources": [...]} (values are dicts). Robust to which file we ended up on.
            sample = next(iter(loaded.values()), None)
            if isinstance(sample, list) or sample is None:
                return loaded
            index = {}
            for key, data in loaded.items():
                if not isinstance(data, dict):
                    continue
                lemma = key.split("|")[0]
                for src in data.get("sources", []):
                    index.setdefault(src, []).append(lemma)
            return index
        except Exception as e:
            print(f"Error loading graduate index: {e}")
        return {}

    def _load_analyzed_filenames(self):
        """Loads the set of filenames that have been analyzed (Smart Caching).

        Prefers the tiny `analyzed_files.json` sidecar (~0.1 MB) the analyzer writes; on a big
        library that is ~200x faster than parsing the multi-hundred-MB `word_stats.json`, which used
        to freeze this window on open and on the 4s poll. Falls back to `word_stats.json` for result
        folders produced before the sidecar existed."""
        try:
            # project_root is two levels up from data/<lang>
            project_root = os.path.dirname(os.path.dirname(self.data_root))
            results_dir = os.path.join(project_root, "results")
            sidecar = os.path.join(results_dir, "analyzed_files.json")
            stats_path = os.path.join(results_dir, "word_stats.json")

            # Sidecar first (fast path), but only when it's at least as new as word_stats.json — a
            # stale sidecar from an interrupted run is ignored in favour of the fresh full stats file.
            source_path = self._fresher_source(sidecar, stats_path)

            if not os.path.exists(source_path):
                self.analyzed_filenames = set()
                self._last_stats_mtime = 0
                self._last_stats_size = 0
                self._last_stats_source = None
                return

            # Smart caching: check mtime and size before parsing. Also key on which file we read, so
            # switching from the fallback to a freshly-written sidecar isn't masked by a stale mtime.
            current_mtime = os.path.getmtime(source_path)
            current_size = os.path.getsize(source_path)

            if (current_mtime == self._last_stats_mtime and current_size == self._last_stats_size
                    and getattr(self, "_last_stats_source", None) == source_path):
                return  # No changes, skip reload

            with open(source_path, 'r', encoding='utf-8') as f:
                loaded = json.load(f)

            # Parse by SHAPE, not filename: the sidecar is a list of basenames; word_stats.json is a
            # dict of word -> {"sources": [...]}. Type detection keeps this correct even if a file is
            # unexpected/legacy.
            if isinstance(loaded, list):
                new_analyzed = set(loaded)
            elif isinstance(loaded, dict):
                new_analyzed = set()
                for data in loaded.values():
                    if isinstance(data, dict):
                        for s in data.get("sources", []):
                            new_analyzed.add(s)
            else:
                new_analyzed = set()

            self.analyzed_filenames = new_analyzed
            self._last_stats_mtime = current_mtime
            self._last_stats_size = current_size
            self._last_stats_source = source_path

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
