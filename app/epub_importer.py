import os
import sys

# Ensure package root is in sys.path
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import warnings
import re

# Suppress EbookLib FutureWarnings/UserWarnings
warnings.filterwarnings("ignore", category=UserWarning, module='ebooklib')

try:
    import ebooklib
    from ebooklib import epub
    from bs4 import BeautifulSoup
except ImportError:
    pass

from app.path_utils import get_user_file

from app.path_utils import get_user_file

# --- Configuration ---
PROCESSED_DIR = get_user_file("data/Processed")

# Colors for Dark Mode
BG_COLOR = "#1e1e1e"
SURFACE_COLOR = "#2d2d2d"
TEXT_COLOR = "#e0e0e0"
ACCENT_COLOR = "#bb86fc"
SECONDARY_COLOR = "#03dac6"

class EpubImporterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Surasura - EPUB Extractor")
        self.root.geometry("600x450")
        self.root.configure(bg=BG_COLOR)
        
        self.style = ttk.Style()
        self.apply_dark_theme()
        
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
        
    def apply_dark_theme(self):
        # Configure general style
        self.style.theme_use('default')
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
            background=[('active', ACCENT_COLOR), ('pressed', ACCENT_COLOR)],
            foreground=[('active', BG_COLOR), ('pressed', BG_COLOR)]
        )
        
        self.style.configure("TRadiobutton", background=BG_COLOR, foreground=TEXT_COLOR, focuscolor=ACCENT_COLOR)
        self.style.map("TRadiobutton",
            foreground=[('active', ACCENT_COLOR)],
            background=[('active', BG_COLOR)]
        )

    def setup_ui(self):
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # File Selection
        ttk.Label(main_frame, text="Select EPUB File:").grid(row=0, column=0, sticky=tk.W, pady=(0, 5))
        self.file_path_var = tk.StringVar()
        ttk.Entry(main_frame, textvariable=self.file_path_var, width=50).grid(row=1, column=0, columnspan=2, sticky=tk.EW, pady=(0, 10))
        ttk.Button(main_frame, text="Browse...", command=self.browse_file).grid(row=1, column=2, padx=(5, 0), pady=(0, 10))

        # Output Name
        ttk.Label(main_frame, text="Output Folder/Base Name:").grid(row=2, column=0, sticky=tk.W, pady=(0, 5))
        self.output_name_var = tk.StringVar()
        ttk.Entry(main_frame, textvariable=self.output_name_var, width=50).grid(row=3, column=0, columnspan=2, sticky=tk.EW, pady=(0, 20))

        # Split Options
        split_frame = ttk.LabelFrame(main_frame, text="Splitting Options", padding="15")
        split_frame.grid(row=4, column=0, columnspan=3, sticky=tk.EW, pady=(0, 20))

        self.split_method_var = tk.StringVar(value="delimiter")
        
        ttk.Radiobutton(split_frame, text="By Delimiter (Regex)", variable=self.split_method_var, value="delimiter", command=self.update_split_ui).grid(row=0, column=0, sticky=tk.W)
        ttk.Radiobutton(split_frame, text="By Length (Chars)", variable=self.split_method_var, value="length", command=self.update_split_ui).grid(row=1, column=0, sticky=tk.W)

        self.split_value_label = ttk.Label(split_frame, text="Regex Pattern:")
        self.split_value_label.grid(row=2, column=0, sticky=tk.W, pady=(10, 0))
        
        self.split_value_var = tk.StringVar(value=r"\n\d+\n")
        self.split_value_entry = ttk.Entry(split_frame, textvariable=self.split_value_var, width=30)
        self.split_value_entry.grid(row=3, column=0, sticky=tk.W, pady=(5, 0))

        # Import Button
        ttk.Button(main_frame, text="Extract and Import", command=self.process_import).grid(row=5, column=0, columnspan=3, pady=(10, 0))

        # Status Label
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(main_frame, textvariable=self.status_var, foreground="#888").grid(row=6, column=0, columnspan=3, pady=(10, 0))

    def update_split_ui(self):
        method = self.split_method_var.get()
        if method == "delimiter":
            self.split_value_label.config(text="Regex Pattern (e.g. \\n\\d+\\n):")
            if not self.split_value_var.get() or self.split_value_var.get() == "1500":
                self.split_value_var.set(r"\n\d+\n")
        else:
            self.split_value_label.config(text="Character Limit (e.g. 1500):")
            if self.split_value_var.get() == r"\n\d+\n":
                self.split_value_var.set("1500")

    def browse_file(self):
        file_path = filedialog.askopenfilename(
            title="Select EPUB file",
            filetypes=[("EPUB files", "*.epub"), ("All files", "*.*")]
        )
        if file_path:
            self.file_path_var.set(file_path)
            # Default name
            if not self.output_name_var.get():
                base = os.path.splitext(os.path.basename(file_path))[0]
                self.output_name_var.set(base)

    def process_import(self):
        epub_path = self.file_path_var.get()
        output_name = self.output_name_var.get().strip()
        split_method = self.split_method_var.get()
        split_value = self.split_value_var.get()

        if not epub_path or not os.path.exists(epub_path):
            messagebox.showerror("Error", "Please select a valid EPUB file.")
            return
        if not output_name:
            messagebox.showerror("Error", "Please enter an output name.")
            return

        try:
            self.status_var.set("Extracting text...")
            self.root.update_idletasks()
            
            full_text, error = self.convert_epub_to_text(epub_path)
            if error:
                messagebox.showerror("Extraction Error", error)
                return

            self.status_var.set("Splitting text...")
            self.root.update_idletasks()
            
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
                messagebox.showinfo("Success", f"Extraction complete!\nSaved {len(chunks)} files to:\n{save_dir}")
                self.root.destroy() # Close window on completion

        except Exception as e:
            messagebox.showerror("Unexpected Error", str(e))
        finally:
            # Check if root still exists (in case destroy() was called or failed before destroy)
            try:
                if self.root.winfo_exists():
                    self.status_var.set("Ready")
            except tk.TclError:
                pass # Root already destroyed

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
                
                # Remove Furigana (rt and rp tags)
                for rt in soup.find_all('rt'):
                    rt.decompose()
                for rp in soup.find_all('rp'):
                    rp.decompose()

                # 1. Handle <br>
                for br in soup.find_all('br'):
                    br.replace_with('\n')
                    
                # 2. Append newlines to block elements
                block_tags = ['p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'li']
                for tag in soup.find_all(block_tags):
                    tag.append('\n')

                # Extract text without BS4 delimiter (to keep words with ruby/span intact)
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
        for i in range(0, len(text), limit):
            chunks.append(text[i:i+limit].strip())
        return [c for c in chunks if c]

    def save_chunks(self, chunks, base_name):
        output_sub_dir = os.path.join(PROCESSED_DIR, base_name)
        if not os.path.exists(output_sub_dir):
            os.makedirs(output_sub_dir)
            
        try:
            for i, chunk in enumerate(chunks, 1):
                filename = f"{base_name}_{i:02d}.txt"
                path = os.path.join(output_sub_dir, filename)
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(chunk)
            return output_sub_dir, None
        except Exception as e:
            return None, str(e)

def main():
    if not os.path.exists(PROCESSED_DIR):
        os.makedirs(PROCESSED_DIR)
        
    root = tk.Tk()
    app = EpubImporterApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
