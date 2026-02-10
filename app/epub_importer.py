import os
import sys

# Ensure package root is in sys.path
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import warnings
import re
try:
    import ebooklib
    from ebooklib import epub
    from bs4 import BeautifulSoup
except ImportError:
    pass

from app.path_utils import get_user_file, get_data_path
from app.anki_utils import load_anki_data, extract_field_text, cleanup_temp_dir

# --- Configuration ---
# PROCESSED_DIR will be determined by the instance based on language

# Colors for Dark Mode
BG_COLOR = "#1e1e1e"
SURFACE_COLOR = "#2d2d2d"
TEXT_COLOR = "#e0e0e0"
ACCENT_COLOR = "#bb86fc"
SECONDARY_COLOR = "#03dac6"
ERROR_COLOR = "#cf6679"

class FileImporterApp:
    def __init__(self, root, language='ja'):
        self.root = root
        self.language = language
        self.processed_dir = os.path.join(get_data_path(language), "Processed")
        self.root.title(f"Surasura - File Importer v1.0 ({language})")
        self.root.geometry("600x650") # Expanded for Anki preview/warning
        self.root.resizable(True, True)
        self.root.minsize(500, 500)
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
        
        # Set Application Icon
        try:
            from app.path_utils import get_icon_path
            icon_path = get_icon_path()
            if os.path.exists(icon_path):
                self.icon_photo = tk.PhotoImage(file=icon_path)
                self.root.iconphoto(False, self.icon_photo)
        except Exception as e:
            print(f"Warning: Could not set icon: {e}")

        self.setup_ui()
        
        # Add trace for dynamic UI
        self.file_path_var.trace_add("write", self.on_file_change)

        # Load Logic Settings
        self.logic_settings = {}
        try:
            settings_path = get_user_file("settings.json")
            if os.path.exists(settings_path):
                import json
                with open(settings_path, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                    self.logic_settings = settings.get("logic", {})
        except Exception:
            pass

    def __del__(self):
        if hasattr(self, 'anki_temp_dir') and self.anki_temp_dir:
            cleanup_temp_dir(self.anki_temp_dir)
        
    def apply_dark_theme(self):
        # Configure general style
        self.style.theme_use('default')
        
        # Cross-platform Fix for TCombobox Dropdown (Listbox) Visibility
        self.root.option_add('*TCombobox*Listbox.background', SURFACE_COLOR)
        self.root.option_add('*TCombobox*Listbox.foreground', TEXT_COLOR)
        self.root.option_add('*TCombobox*Listbox.selectBackground', ACCENT_COLOR)
        self.root.option_add('*TCombobox*Listbox.selectForeground', BG_COLOR)
        self.root.option_add('*TCombobox*Listbox.font', ('Segoe UI', 10))
        self.style.configure(".", 
            background=BG_COLOR, 
            foreground=TEXT_COLOR, 
            fieldbackground=SURFACE_COLOR,
            font=('Segoe UI', 10)
        )
        
        self.style.configure("TFrame", background=BG_COLOR)
        self.style.configure("TLabelframe", background=BG_COLOR, bordercolor=SURFACE_COLOR)
        self.style.configure("TLabelframe.Label", background=BG_COLOR, foreground=ACCENT_COLOR, font=('Segoe UI', 10, 'bold'))
        
        self.style.configure("TLabel", background=BG_COLOR, foreground=TEXT_COLOR)
        
        self.style.configure("TEntry", 
            fieldbackground=SURFACE_COLOR, 
            foreground=TEXT_COLOR, 
            insertcolor=TEXT_COLOR,
            borderwidth=0
        )
        
        self.style.configure("TButton", 
            background=SURFACE_COLOR, 
            foreground=TEXT_COLOR, 
            borderwidth=0,
            focuscolor=ACCENT_COLOR
        )
        self.style.map("TButton",
            background=[('active', ACCENT_COLOR), ('pressed', ACCENT_COLOR), ('disabled', SURFACE_COLOR)],
            foreground=[('active', BG_COLOR), ('pressed', BG_COLOR), ('disabled', '#555')]
        )
        
        self.style.configure("TRadiobutton", background=BG_COLOR, foreground=TEXT_COLOR, focuscolor=ACCENT_COLOR)
        self.style.map("TRadiobutton",
            foreground=[('active', ACCENT_COLOR)],
            background=[('active', BG_COLOR)]
        )

        self.style.configure("TCheckbutton", background=BG_COLOR, foreground=TEXT_COLOR)
        self.style.map("TCheckbutton",
            foreground=[('active', ACCENT_COLOR)],
            background=[('active', BG_COLOR)]
        )

    def setup_ui(self):
        self.main_frame = ttk.Frame(self.root, padding="20")
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        # File Selection
        ttk.Label(self.main_frame, text="Select File (APKG, EPUB, TXT, MD, SRT):").pack(anchor=tk.W, pady=(0, 5))
        
        file_sel_frame = ttk.Frame(self.main_frame)
        file_sel_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.file_path_var = tk.StringVar()
        ttk.Entry(file_sel_frame, textvariable=self.file_path_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(file_sel_frame, text="Browse...", command=self.browse_file).pack(side=tk.LEFT, padx=(5, 0))

        # Output Name (Shared)
        ttk.Label(self.main_frame, text="Output Folder/Base Name:").pack(anchor=tk.W, pady=(0, 5))
        self.output_name_var = tk.StringVar()
        ttk.Entry(self.main_frame, textvariable=self.output_name_var).pack(fill=tk.X, pady=(0, 20))

        # --- OPTION CONTAINERS ---
        self.options_container = ttk.Frame(self.main_frame)
        self.options_container.pack(fill=tk.BOTH, expand=True)

        # 1. STANDARD OPTIONS (Split)
        self.standard_options_frame = ttk.Frame(self.options_container)
        
        split_frame = ttk.LabelFrame(self.standard_options_frame, text="Splitting Options", padding="15")
        split_frame.pack(fill=tk.X, pady=(0, 20))

        self.split_method_var = tk.StringVar(value="delimiter")
        
        ttk.Radiobutton(split_frame, text="By Delimiter (Regex)", variable=self.split_method_var, value="delimiter", command=self.update_split_ui).pack(anchor=tk.W)
        ttk.Radiobutton(split_frame, text="By Length (Chars)", variable=self.split_method_var, value="length", command=self.update_split_ui).pack(anchor=tk.W)

        self.split_value_label = ttk.Label(split_frame, text="Regex Pattern:")
        self.split_value_label.pack(anchor=tk.W, pady=(10, 0))
        
        # Load default split length from settings
        default_split = 1500
        try:
            import json
            settings_path = get_user_file("settings.json")
            if os.path.exists(settings_path):
                with open(settings_path, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                    default_split = settings.get("split_length", 1500)
        except Exception:
            pass
            
        self.split_value_var = tk.StringVar(value=str(default_split)) # Start with settings value
        self.split_value_entry = ttk.Entry(split_frame, textvariable=self.split_value_var)
        self.split_value_entry.pack(fill=tk.X, pady=(5, 0))

        # 2. ANKI OPTIONS
        self.anki_options_frame = ttk.Frame(self.options_container)
        
        ttk.Label(self.anki_options_frame, text="Select field containing sentences:").pack(anchor=tk.W, pady=(0, 5))
        self.anki_field_var = tk.StringVar()
        self.anki_field_combo = ttk.Combobox(self.anki_options_frame, textvariable=self.anki_field_var, state="readonly")
        self.anki_field_combo.pack(fill=tk.X, pady=(0, 10))
        self.anki_field_combo.bind("<<ComboboxSelected>>", self.update_anki_preview)
        
        ttk.Label(self.anki_options_frame, text="Example Preview:").pack(anchor=tk.W, pady=(0, 5))
        self.anki_preview_text = tk.Text(self.anki_options_frame, height=4, bg=SURFACE_COLOR, fg="#888", font=("Segoe UI", 9), relief=tk.FLAT, borderwidth=0)
        self.anki_preview_text.pack(fill=tk.X, pady=(0, 15))
        self.anki_preview_text.config(state=tk.DISABLED)

        warning_text = (
            "WARNING: Only use an Anki Deck if it is 100% immersion content. "
            "Otherwise your content frequency list will be innacurate. \n\n"
            "This is simply an alternative to uploading subtitles / VN text."
        )
        warn_label = tk.Label(self.anki_options_frame, text=warning_text, foreground=ERROR_COLOR, 
                             background=BG_COLOR, justify=tk.LEFT, wraplength=550, font=("Segoe UI", 9, "bold"))
        warn_label.pack(fill=tk.X, pady=(0, 10))
        
        self.understand_var = tk.BooleanVar(value=False)
        self.chk_understand = ttk.Checkbutton(self.anki_options_frame, text="I Understand", 
                                             variable=self.understand_var, command=self.update_btn_state)
        self.chk_understand.pack(anchor=tk.W, pady=(0, 10))

        # Bottom UI
        self.import_btn = ttk.Button(self.main_frame, text="Extract and Import", command=self.process_import)
        self.import_btn.pack(pady=(10, 0))

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(self.main_frame, textvariable=self.status_var, foreground="#888").pack(pady=(10, 0))

        # Initial View
        self.standard_options_frame.pack(fill=tk.BOTH, expand=True)

    def on_file_change(self, *args):
        path = self.file_path_var.get()
        if not path:
            return
            
        is_anki = path.lower().endswith('.apkg')
        
        if is_anki:
            self.standard_options_frame.pack_forget()
            self.anki_options_frame.pack(fill=tk.BOTH, expand=True)
            self.load_anki_schema(path)
        else:
            self.anki_options_frame.pack_forget()
            self.standard_options_frame.pack(fill=tk.BOTH, expand=True)
            self.clear_anki_data()
        
        self.update_btn_state()

    def clear_anki_data(self):
        if self.anki_temp_dir:
            cleanup_temp_dir(self.anki_temp_dir)
            self.anki_temp_dir = None
        self.anki_notes = []
        self.anki_fields = []
        self.anki_model_map = {}
        self.anki_field_var.set("")
        self.anki_field_combo['values'] = []
        self.anki_preview_text.config(state=tk.NORMAL)
        self.anki_preview_text.delete(1.0, tk.END)
        self.anki_preview_text.config(state=tk.DISABLED)

    def load_anki_schema(self, path):
        if not os.path.exists(path):
            return
        try:
            self.status_var.set("Reading Anki Deck schema...")
            self.root.update_idletasks()
            
            # Cleanup previous
            if self.anki_temp_dir:
                cleanup_temp_dir(self.anki_temp_dir)
            
            self.anki_fields, self.anki_notes, self.anki_model_map, self.anki_temp_dir = load_anki_data(path)
            self.anki_field_combo['values'] = self.anki_fields
            
            # Auto-select "Sentence" or "Expression" if they exist
            if "Sentence" in self.anki_fields:
                self.anki_field_var.set("Sentence")
            elif "Expression" in self.anki_fields:
                self.anki_field_var.set("Expression")
            
            self.update_anki_preview()
            self.status_var.set("Ready")
        except Exception as e:
            messagebox.showerror("Anki Error", f"Failed to load Anki data:\n{e}")
            self.status_var.set("Error")

    def update_anki_preview(self, event=None):
        field = self.anki_field_var.get()
        if not field or not self.anki_notes:
            return
            
        # Extract a small sample
        sample_text = extract_field_text(self.anki_notes[:10], self.anki_model_map, field)
        
        self.anki_preview_text.config(state=tk.NORMAL)
        self.anki_preview_text.delete(1.0, tk.END)
        self.anki_preview_text.insert(tk.END, sample_text)
        self.anki_preview_text.config(state=tk.DISABLED)

    def update_btn_state(self):
        is_anki = self.file_path_var.get().lower().endswith('.apkg')
        if is_anki:
            if self.understand_var.get():
                self.import_btn.config(state=tk.NORMAL)
            else:
                self.import_btn.config(state=tk.DISABLED)
        else:
            self.import_btn.config(state=tk.NORMAL)

    def update_split_ui(self):
        method = self.split_method_var.get()
        if method == "delimiter":
            self.split_value_label.config(text="Regex Pattern (e.g. \\n\\d+\\n):")
            if not self.split_value_var.get() or self.split_value_var.get().isdigit():
                self.split_value_var.set(r"\n\d+\n")
        else:
            self.split_value_label.config(text="Character Limit (e.g. 1500):")
            # If current value is NOT a number, reset to setting default
            if not self.split_value_var.get().isdigit():
                try:
                    import json
                    settings_path = get_user_file("settings.json")
                    with open(settings_path, 'r', encoding='utf-8') as f:
                        settings = json.load(f)
                        self.split_value_var.set(str(settings.get("split_length", 1500)))
                except Exception:
                    self.split_value_var.set("1500")

    def browse_file(self):
        file_path = filedialog.askopenfilename(
            title="Select File",
            filetypes=[
                ("Supported files", "*.epub *.txt *.md *.srt *.apkg"),
                ("Anki Decks", "*.apkg"),
                ("EPUB files", "*.epub"),
                ("Text files", "*.txt *.md"),
                ("Subtitle files", "*.srt"),
                ("All files", "*.*")
            ]
        )
        if file_path:
            self.file_path_var.set(file_path)
            # Default name
            if not self.output_name_var.get():
                base = os.path.splitext(os.path.basename(file_path))[0]
                self.output_name_var.set(base)

    def process_import(self):
        file_path = self.file_path_var.get()
        output_name = self.output_name_var.get().strip()
        
        if not file_path or not os.path.exists(file_path):
            messagebox.showerror("Error", "Please select a valid file.")
            return
        if not output_name:
            messagebox.showerror("Error", "Please enter an output name.")
            return

        is_anki = file_path.lower().endswith('.apkg')
        
        if is_anki and not self.understand_var.get():
            messagebox.showwarning("Incomplete", "Please confirm you understand the warning before extracting Anki Decks.")
            return

        try:
            self.status_var.set("Extracting text...")
            self.root.update_idletasks()
            
            if is_anki:
                selected_field = self.anki_field_var.get()
                if not selected_field:
                    messagebox.showerror("Error", "Please select an Anki field to extract.")
                    return
                full_text = extract_field_text(self.anki_notes, self.anki_model_map, selected_field)
                chunks = [full_text]
            else:
                full_text, error = self.extract_text_from_file(file_path)
                if error:
                    messagebox.showerror("Extraction Error", error)
                    return

                self.status_var.set("Splitting text...")
                self.root.update_idletasks()
                
                split_method = self.split_method_var.get()
                split_value = self.split_value_var.get()
                
                if split_method == "delimiter":
                    chunks = self.split_by_delimiter(full_text, split_value)
                else:
                    try:
                        limit = int(split_value)
                        chunks = self.split_by_length(full_text, limit)
                    except ValueError:
                        messagebox.showerror("Error", "Length must be a number.")
                        return

            self.status_var.set(f"Saving {len(chunks)} files...")
            self.root.update_idletasks()
            
            save_dir, save_error = self.save_chunks(chunks, output_name)
            
            if save_error:
                messagebox.showerror("Save Error", save_error)
            else:
                self.status_var.set("Success!")
                messagebox.showinfo("Success", 
                    f"Extraction complete!\nSaved {len(chunks)} files to:\n{save_dir}\n\n"
                    "👉 PLEASE MOVE the desired files from this folder into the "
                    "HighPriority, LowPriority, or GoalContent folders for analysis.")
                self.root.destroy() 

        except Exception as e:
            messagebox.showerror("Unexpected Error", str(e))
        finally:
            try:
                if self.root.winfo_exists():
                    self.status_var.set("Ready")
            except tk.TclError:
                pass

    def extract_text_from_file(self, file_path):
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".epub":
            return self.convert_epub_to_text(file_path)
        elif ext == ".srt":
            return self.extract_text_from_srt(file_path)
        else:
            return self.extract_text_from_generic(file_path)

    def extract_text_from_generic(self, file_path):
        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                text = f.read()
            return text, None
        except Exception as e:
            return None, f"Failed to read file: {e}"

    def contains_cjk(self, text):
        # Matches Hiragana, Katakana, and CJK Unified Ideographs (Common + Rare + Ext A)
        # Included: \u4E00-\u9FFF to cover common Chinese/Japanese Kanji
        pattern = re.compile(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]')
        return bool(pattern.search(text))

    def extract_text_from_srt(self, file_path):
        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            
            lines = content.splitlines()
            cleaned_lines = []
            timestamp_re = re.compile(r'\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,.]\d{3}')
            
            for line in lines:
                line = line.strip()
                if not line or line.isdigit() or timestamp_re.match(line):
                    continue
                if self.contains_cjk(line):
                    cleaned_lines.append(line)
            
            return "\n".join(cleaned_lines), None
        except Exception as e:
            return None, f"Failed to parse SRT: {e}"

    def convert_epub_to_text(self, epub_path):
        try:
            book = epub.read_epub(epub_path)
        except Exception as e:
            return None, f"Failed to read EPUB: {e}"

        full_text_list = []
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            try:
                content = item.get_content()
                soup = BeautifulSoup(content, 'html.parser')
                
                for rt in soup.find_all('rt'): rt.decompose()
                for rp in soup.find_all('rp'): rp.decompose()
                for br in soup.find_all('br'): br.replace_with('\n')
                    
                block_tags = ['p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'li']
                for tag in soup.find_all(block_tags): tag.append('\n')

                text = soup.get_text(separator='')
                lines = [line.strip() for line in text.splitlines() if line.strip()]
                cleaned_text = "\n".join(lines)
                if cleaned_text:
                    full_text_list.append(cleaned_text)
            except Exception as e:
                print(f"Warning: Failed to parse item {item.get_name()}: {e}")

        return "\n\n".join(full_text_list), None

    def split_by_delimiter(self, text, pattern):
        if "(" not in pattern:
            pattern = f"({pattern})"
        parts = re.split(pattern, text)
        chunks = []
        current_chunk = parts[0]
        for i in range(1, len(parts), 2):
            delimiter = parts[i]
            following_text = parts[i+1] if i+1 < len(parts) else ""
            if current_chunk.strip():
                chunks.append(current_chunk.strip())
            current_chunk = delimiter + following_text
        if current_chunk.strip():
            chunks.append(current_chunk.strip())
        return chunks

    def split_by_length(self, text, limit):
        chunks = []
        pos = 0
        total_len = len(text)
        overflow_limit = self.logic_settings.get("importer", {}).get("split_overflow", 150)
        boundaries = "。？！.?! \n"
        closing_marks = "」』)\"']}"
        
        while pos < total_len:
            target_end = pos + limit
            if target_end >= total_len:
                chunks.append(text[pos:].strip())
                break
            found_boundary = -1
            search_end = min(target_end + overflow_limit, total_len)
            for i in range(target_end, search_end):
                if text[i] in boundaries:
                    actual_end = i + 1
                    while actual_end < total_len and text[actual_end] in closing_marks:
                        actual_end += 1
                    found_boundary = actual_end
                    break
            end_pos = found_boundary if found_boundary != -1 else search_end
            chunks.append(text[pos:end_pos].strip())
            pos = end_pos
        return [c for c in chunks if c]

    def save_chunks(self, chunks, base_name):
        output_sub_dir = os.path.join(self.processed_dir, base_name)
        if not os.path.exists(output_sub_dir):
            os.makedirs(output_sub_dir)
        try:
            for i, chunk in enumerate(chunks, 1):
                filename = f"{base_name}_{i:02d}.txt" if len(chunks) > 1 else f"{base_name}.txt"
                path = os.path.join(output_sub_dir, filename)
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(chunk)
            return output_sub_dir, None
        except Exception as e:
            return None, str(e)

def main():
    import argparse
    parser = argparse.ArgumentParser(description="File Importer")
    parser.add_argument("--language", default='ja', help="Target language (default: ja)")
    args = parser.parse_args()

    processed_dir = os.path.join(get_data_path(args.language), "Processed")
    if not os.path.exists(processed_dir):
        os.makedirs(processed_dir)
        
    root = tk.Tk()
    app = FileImporterApp(root, language=args.language)
    root.mainloop()

if __name__ == "__main__":
    main()
