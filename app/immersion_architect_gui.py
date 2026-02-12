import tkinter as tk
from tkinter import ttk, messagebox
import threading
from app.immersion_architect import ImmersionArchitect

class ImmersionArchitectGui(tk.Toplevel):
    def __init__(self, parent_root):
        super().__init__(parent_root)
        self.title("Immersion Architect Intelligence")
        self.geometry("700x600")
        self.resizable(True, True)
        
        # Bind Escape key to close window
        self.bind("<Escape>", lambda e: self.destroy())
        
        # Theme Integration (Attempt to match parent colors if available)
        # Using hardcoded dark theme constants from main.py for now since we don't have direct access
        # or we could pass them in. Let's use standard defaults that look okay-ish.
        self.config(bg="#1e1e1e")
        self.style = ttk.Style()
        # Assumes style 'default' or similar is already configured by main app
        
        self.log_queue = []
        self.is_running = False
        
        self.setup_ui()
        
    def setup_ui(self):
        # Main Container
        main_frame = ttk.Frame(self, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # HEADER
        header_frame = ttk.Frame(main_frame)
        header_frame.pack(fill=tk.X, pady=(0, 20))
        
        lbl_title = ttk.Label(header_frame, text="Immersion Architect", font=("Segoe UI", 16, "bold"), foreground="#bb86fc")
        lbl_title.pack(side=tk.LEFT)
        
        # DESCRIPTION
        desc_text = ("This intelligence engine will re-sort your entire library based on 'Yield vs Cost'.\n"
                     "It creates a virtual path that maximizes your vocabulary acquisition speed.\n"
                     "Your physical files will NOT be moved.")
        lbl_desc = ttk.Label(header_frame, text=desc_text, font=("Segoe UI", 10), foreground="#e0e0e0")
        lbl_desc.pack(side=tk.LEFT, padx=(20, 0))

        # CONTROLS AREA
        controls_frame = ttk.Frame(main_frame)
        controls_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Launch Button
        self.btn_launch = ttk.Button(controls_frame, text="Launch Intelligence", command=self.start_simulation, style="Action.TButton")
        self.btn_launch.pack(side=tk.LEFT)
        
        # Spinner (Hidden by default)
        self.spinner = ttk.Progressbar(controls_frame, mode='indeterminate', length=200)
        
        # LOG CONSOLE
        log_frame = ttk.LabelFrame(main_frame, text=" Engine Logs", padding="10")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        self.log_text = tk.Text(log_frame, height=8, bg="#2d2d2d", fg="#e0e0e0", 
                                font=("Consolas", 9), relief=tk.FLAT, state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        # RESULTS PREVIEW (Hidden initially? Or just empty)
        self.results_frame = ttk.LabelFrame(main_frame, text=" Virtual Learning Path Preview", padding="10")
        self.results_frame.pack(fill=tk.BOTH, expand=True)
        
        # Tabs for Phases
        self.notebook = ttk.Notebook(self.results_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        
        self.tab_now = self.create_file_list_tab("PHASE 1: NOW (Urgent)")
        self.tab_soon = self.create_file_list_tab("PHASE 2: SOON (Growth)")
        self.tab_later = self.create_file_list_tab("PHASE 3: LATER (Long Tail)")
        
        self.notebook.add(self.tab_now, text=" 01 NOW ")
        self.notebook.add(self.tab_soon, text=" 02 SOON ")
        self.notebook.add(self.tab_later, text=" 03 LATER ")

        # FOOTER ACTIONS
        footer_frame = ttk.Frame(main_frame)
        footer_frame.pack(fill=tk.X, pady=(10, 0))
        
        self.var_warning = tk.BooleanVar(value=False)
        chk_warning = ttk.Checkbutton(footer_frame, text="WARNING: This will overwrite your existing reading order.", 
                                      variable=self.var_warning, command=self.toggle_commit_button)
        chk_warning.pack(side=tk.LEFT)
        
        self.btn_commit = ttk.Button(footer_frame, text="Commit Sort", state=tk.DISABLED, command=self.commit_sort)
        self.btn_commit.pack(side=tk.RIGHT)
        
    def create_file_list_tab(self, title):
        frame = ttk.Frame(self.notebook)
        
        # Treeview to list files
        columns = ("Title", "Reason")
        tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="none")
        tree.heading("Title", text="Title / File")
        tree.heading("Reason", text="Reason")
        tree.column("Title", width=300)
        tree.column("Reason", width=150)
        
        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Store reference to tree to populate later
        frame.tree = tree
        return frame

    def log(self, message):
        def _update():
            self.log_text.config(state=tk.NORMAL)
            self.log_text.insert(tk.END, "> " + message + "\n")
            self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)
        self.after(0, _update)

    def start_simulation(self):
        self.btn_launch.config(state=tk.DISABLED)
        self.spinner.pack(side=tk.LEFT, padx=10)
        self.spinner.start(10)
        self.is_running = True
        
        # Clear previous results
        for tab in [self.tab_now, self.tab_soon, self.tab_later]:
            for item in tab.tree.get_children():
                tab.tree.delete(item)
        
        threading.Thread(target=self._run_engine_thread, daemon=True).start()

    def _run_engine_thread(self):
        architect = ImmersionArchitect(callback_log=self.log)
        architect.index_corpus()
        phases = architect.simulate_sort()
        
        self.after(0, lambda: self.display_results(phases))

    def display_results(self, phases):
        self.spinner.stop()
        self.spinner.pack_forget()
        self.btn_launch.config(state=tk.NORMAL)
        self.is_running = False
        
        self.log("Populating Preview...")
        
        self._populate_tree(self.tab_now.tree, phases.get("PHASE_1_NOW", []))
        self._populate_tree(self.tab_soon.tree, phases.get("PHASE_2_SOON", []))
        self._populate_tree(self.tab_later.tree, phases.get("PHASE_3_LATER", []))
        
        self.log("Ready to Commit.")

    def _populate_tree(self, tree, details_list):
        for item in details_list:
            tree.insert("", tk.END, values=(item["title"], item["reason"]))

    def toggle_commit_button(self):
        if self.var_warning.get():
            self.btn_commit.config(state=tk.NORMAL)
        else:
            self.btn_commit.config(state=tk.DISABLED)
            
    def commit_sort(self):
        messagebox.showinfo("Success", "Manifest generated successfully!\n(This is a dummy action for now)")
        self.destroy()
