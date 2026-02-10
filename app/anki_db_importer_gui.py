import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import json
from datetime import datetime

# Ensure package root is in sys.path
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.path_utils import get_user_file, get_user_files_path, get_icon_path
from app.anki_utils import load_anki_data, extract_field_text, cleanup_temp_dir
from app.analyzer import JapaneseTokenizer, ChineseTokenizer

# Colors for Dark Mode (Matching Content Importer)
BG_COLOR = "#1e1e1e"
SURFACE_COLOR = "#2d2d2d"
TEXT_COLOR = "#ffffff"
ACCENT_COLOR = "#bb86fc"
SUCCESS_COLOR = "#03dac6"
ERROR_COLOR = "#cf6679"

class AnkiImporterApp:
    def __init__(self, root, language='ja'):
        self.root = root
        self.language = language
        self.root.title(f"Surasura - Anki to Known Words ({language})")
        self.root.geometry("600x620")
        self.root.resizable(True, True)
        self.root.minsize(550, 600)
        self.root.configure(bg=BG_COLOR)
        
        # Bind Escape key to close
        self.root.bind("<Escape>", lambda e: self.root.destroy())
        self.style = ttk.Style()
        self.apply_dark_theme()
        
        # Anki State
        self.anki_notes = []
        self.anki_fields = []
        self.anki_model_map = {}
        self.anki_temp_dir = None
        
        # UI State Variables
        self.file_path_var = tk.StringVar()
        self.anki_field_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Ready")

        # UI Elements (Declared for linter and safety)
        self.file_frame = None
        self.anki_options_frame = None
        self.anki_field_combo = None
        self.anki_preview_text = None
        self.extract_btn = None
        self.icon_photo = None
        
        # Set Application Icon
        try:
            icon_path = get_icon_path()
            if os.path.exists(icon_path):
                self.icon_photo = tk.PhotoImage(file=icon_path)
                self.root.iconphoto(False, self.icon_photo)
        except Exception:
            pass

        self.setup_ui()
        
        # Add trace for dynamic UI
        self.file_path_var.trace_add("write", self.on_file_change)

    def __del__(self):
        if hasattr(self, 'anki_temp_dir') and self.anki_temp_dir:
            cleanup_temp_dir(self.anki_temp_dir)
        
    def apply_dark_theme(self):
        self.style.theme_use('clam')
        
        # Cross-platform Fix for TCombobox Dropdown
        self.root.option_add('*TCombobox*Listbox.background', SURFACE_COLOR)
        self.root.option_add('*TCombobox*Listbox.foreground', TEXT_COLOR)
        self.root.option_add('*TCombobox*Listbox.selectBackground', ACCENT_COLOR)
        self.root.option_add('*TCombobox*Listbox.selectForeground', BG_COLOR)
        
        self.style.configure(".", 
            background=BG_COLOR, 
            foreground=TEXT_COLOR, 
            fieldbackground=SURFACE_COLOR,
            troughcolor=BG_COLOR,
            selectbackground=ACCENT_COLOR,
            selectforeground=BG_COLOR,
            font=('Segoe UI', 10)
        )
        
        self.style.configure("TFrame", background=BG_COLOR)
        self.style.configure("TLabelframe", background=BG_COLOR, bordercolor=SURFACE_COLOR)
        self.style.configure("TLabelframe.Label", background=BG_COLOR, foreground=ACCENT_COLOR, font=('Segoe UI', 11, 'bold'))
        self.style.configure("TLabel", background=BG_COLOR, foreground=TEXT_COLOR)
        self.style.configure("Header.TLabel", font=("Segoe UI", 16, "bold"), foreground=SUCCESS_COLOR, background=BG_COLOR)
        self.style.configure("SubHeader.TLabel", font=("Segoe UI", 11, "italic"), foreground=ACCENT_COLOR, background=BG_COLOR)
        
        self.style.configure("TEntry", fieldbackground=SURFACE_COLOR, foreground=TEXT_COLOR, insertcolor=TEXT_COLOR, borderwidth=0)
        
        self.style.configure("TButton", background=SURFACE_COLOR, foreground=TEXT_COLOR, borderwidth=0, focuscolor=ACCENT_COLOR, padding=6)
        self.style.map("TButton",
            background=[('active', ACCENT_COLOR), ('pressed', ACCENT_COLOR), ('disabled', SURFACE_COLOR)],
            foreground=[('active', BG_COLOR), ('pressed', BG_COLOR), ('disabled', '#555')]
        )

    def setup_ui(self):
        main_frame = ttk.Frame(self.root, padding="25")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Header
        header = ttk.Label(main_frame, text="Anki to Known Card Importer", style="Header.TLabel", justify=tk.CENTER)
        header.pack(pady=(0, 5))

        # Sub-instruction
        sub_header = ttk.Label(main_frame, text="> Download the Anki deck with cards you already know", 
                               style="SubHeader.TLabel", justify=tk.CENTER)
        sub_header.pack(pady=(0, 10))

        # Description
        desc = ttk.Label(main_frame, text="This will generate a known-words List", 
                         justify=tk.CENTER, foreground="#aaaaaa")
        desc.pack(pady=(0, 20))

        # File Selection
        self.file_frame = ttk.LabelFrame(main_frame, text=" 1. Select Anki Deck ", padding="15")
        self.file_frame.pack(fill=tk.X, pady=(0, 20))
        
        file_sel_container = ttk.Frame(self.file_frame)
        file_sel_container.pack(fill=tk.X)
        
        ttk.Entry(file_sel_container, textvariable=self.file_path_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(file_sel_container, text="Browse...", command=self.browse_file).pack(side=tk.LEFT, padx=(5, 0))

        # Field Selection (Initially hidden)
        self.anki_options_frame = ttk.LabelFrame(main_frame, text=" 2. Extraction Options ", padding="15")
        # Hidden by default, will be packed on file change
        
        ttk.Label(self.anki_options_frame, text="Select field containing text:").pack(anchor=tk.W, pady=(0, 5))
        self.anki_field_combo = ttk.Combobox(self.anki_options_frame, textvariable=self.anki_field_var, state="readonly")
        self.anki_field_combo.pack(fill=tk.X, pady=(0, 15))
        self.anki_field_combo.bind("<<ComboboxSelected>>", self.update_anki_preview)
        
        ttk.Label(self.anki_options_frame, text="Preview (First few notes):").pack(anchor=tk.W, pady=(0, 5))
        self.anki_preview_text = tk.Text(self.anki_options_frame, height=4, bg=SURFACE_COLOR, fg="#888", 
                                        font=("Segoe UI", 9), relief=tk.FLAT, borderwidth=0, padx=10, pady=10)
        self.anki_preview_text.pack(fill=tk.X, pady=(0, 15))
        self.anki_preview_text.config(state=tk.DISABLED)

        # Bottom UI
        ttk.Label(main_frame, text="Note: All words in the field will be marked as KNOWN", 
                  foreground=ACCENT_COLOR, font=("Segoe UI", 10, "bold"), justify=tk.CENTER).pack(pady=(0, 10))

        self.extract_btn = ttk.Button(main_frame, text="Generate Known Words List", command=self.process_extraction, state=tk.DISABLED)
        self.extract_btn.pack(pady=(10, 0))

        ttk.Label(main_frame, textvariable=self.status_var, foreground="#555").pack(pady=(10, 0))

    def browse_file(self):
        file_path = filedialog.askopenfilename(
            title="Select Anki Deck",
            filetypes=[("Anki Decks", "*.apkg"), ("All files", "*.*")]
        )
        if file_path:
            self.file_path_var.set(file_path)

    def on_file_change(self, *args):
        path = self.file_path_var.get()
        if not path or not os.path.exists(path):
            if self.anki_options_frame: self.anki_options_frame.pack_forget()
            if self.extract_btn: self.extract_btn.config(state=tk.DISABLED)
            return
            
        if path.lower().endswith('.apkg'):
            if self.anki_options_frame: self.anki_options_frame.pack(fill=tk.X, pady=(0, 20))
            self.load_anki_schema(path)
            if self.extract_btn: self.extract_btn.config(state=tk.NORMAL)
        else:
            if self.anki_options_frame: self.anki_options_frame.pack_forget()
            if self.extract_btn: self.extract_btn.config(state=tk.DISABLED)

    def load_anki_schema(self, path):
        try:
            self.status_var.set("Reading Anki Deck schema...")
            self.root.update_idletasks()
            
            if self.anki_temp_dir:
                cleanup_temp_dir(self.anki_temp_dir)
            
            self.anki_fields, self.anki_notes, self.anki_model_map, self.anki_temp_dir = load_anki_data(path)
            if self.anki_field_combo:
                self.anki_field_combo['values'] = self.anki_fields
            
            # Common field names to auto-select
            for pref in ["Sentence", "Expression", "Word", "Front"]:
                if pref in self.anki_fields:
                    self.anki_field_var.set(pref)
                    break
            
            self.update_anki_preview()
            self.status_var.set("Ready")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load Anki data:\n{e}")
            self.status_var.set("Error")

    def update_anki_preview(self, event=None):
        field = self.anki_field_var.get()
        if not field or not self.anki_notes:
            return
            
        sample_text = extract_field_text(self.anki_notes[:5], self.anki_model_map, field)
        
        if self.anki_preview_text:
            self.anki_preview_text.config(state=tk.NORMAL)
            self.anki_preview_text.delete(1.0, tk.END)
            self.anki_preview_text.insert(tk.END, sample_text)
            self.anki_preview_text.config(state=tk.DISABLED)

    def process_extraction(self):
        path = self.file_path_var.get()
        field = self.anki_field_var.get()
        
        if not path or not field:
            return

        confirm = messagebox.askyesno("Confirm", 
            "This will parse all notes in the selected field and create a KnownWord.json list.\n"
            "Existing known words will be preserved if they are already in your list.\n"
            "Continue?")
        
        if not confirm:
            return

        try:
            self.status_var.set("Extracting text...")
            self.root.update_idletasks()
            
            full_text = extract_field_text(self.anki_notes, self.anki_model_map, field)
            
            self.status_var.set("Tokenizing words...")
            self.root.update_idletasks()
            
            tokenizer = JapaneseTokenizer() if self.language == 'ja' else ChineseTokenizer()
            # We don't care about sentences here, just the unique lemmas
            tokens = tokenizer.tokenize(full_text)
            
            # Unique known words
            unique_words = set()
            for lemma, reading, surface in tokens:
                # Basic filtering similar to analyzer
                if not lemma.strip(): continue
                # We save as (lemma, reading)
                unique_words.add((lemma, reading))

            self.status_var.set(f"Updating KnownWord.json with {len(unique_words)} words...")
            self.root.update_idletasks()
            
            self.update_known_words(unique_words)
            
            self.status_var.set("Success!")
            messagebox.showinfo("Success", f"Successfully processed {len(unique_words)} unique words from Anki.\nYour KnownWord.json has been updated.")
            self.root.destroy()
            
        except Exception as e:
            messagebox.showerror("Error", f"Extraction failed:\n{e}")
            self.status_var.set("Error")

    def update_known_words(self, new_known_tuples):
        user_files_dir = get_user_files_path(self.language)
        output_json = os.path.join(user_files_dir, "KnownWord.json")
        
        existing_data = {"words": [], "statistics": {}}
        if os.path.exists(output_json):
            try:
                with open(output_json, 'r', encoding='utf-8') as f:
                    existing_data = json.load(f)
            except Exception:
                pass

        # Handle both list and dict formats for backward compat
        if isinstance(existing_data, list):
            existing_words = existing_data
            existing_data = {"words": existing_words, "statistics": {}}
        else:
            existing_words = existing_data.get("words", [])

        # Create a map for quick lookup and to preserve metadata of existing words
        word_map = {}
        for w in existing_words:
            key = (w.get('dictForm'), w.get('secondary', ''))
            word_map[key] = w

        # Add or update new words
        now_str = datetime.now().isoformat()
        for lemma, reading in new_known_tuples:
            key = (lemma, reading)
            if key in word_map:
                # Keep existing but ensure it's marked KNOWN
                word_map[key]['knownStatus'] = "KNOWN"
            else:
                word_map[key] = {
                    'dictForm': lemma,
                    'secondary': reading,
                    'partOfSpeech': '',
                    'language': self.language,
                    'knownStatus': "KNOWN",
                    'hasCard': 1, # Since it came from Anki
                    'tracked': 0,
                    'created': now_str,
                    'mod': now_str,
                    'isModern': 1
                }

        # Rebuild list
        updated_words = list(word_map.values())
        
        # Update Stats
        stats = {
            'totalWords': len(updated_words),
            'knownWords': sum(1 for w in updated_words if w.get('knownStatus') == "KNOWN"),
            'learningWords': sum(1 for w in updated_words if w.get('knownStatus') == "LEARNING"),
            'unknownWords': sum(1 for w in updated_words if w.get('knownStatus') == "UNKNOWN"),
            'ignoredWords': sum(1 for w in updated_words if w.get('knownStatus') == "IGNORED"),
            'languages': sorted(list(set(w.get('language', self.language) for w in updated_words)))
        }

        json_data = {
            'exportDate': now_str,
            'source': 'Anki Extraction',
            'statistics': stats,
            'words': updated_words
        }

        with open(output_json, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, indent=2, ensure_ascii=False)

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Anki to Known Words")
    parser.add_argument("--language", default='ja', help="Target language (ja, zh)")
    args = parser.parse_args()

    root = tk.Tk()
    app = AnkiImporterApp(root, language=args.language)
    root.mainloop()

if __name__ == "__main__":
    main()
