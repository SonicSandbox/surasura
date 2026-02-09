import tkinter as tk
from tkinter import ttk
import json
from app.path_utils import get_icon_path, get_user_file

# --- Constants & Theme (Matching main app) ---
BG_COLOR = "#1e1e1e"
SURFACE_COLOR = "#2d2d2d"
TEXT_COLOR = "#e0e0e0"
ACCENT_COLOR = "#bb86fc"
SECONDARY_COLOR = "#03dac6"
ERROR_COLOR = "#cf6679"

class OnboardingGuide:
    def __init__(self, parent, on_complete_callback):
        self.window = tk.Toplevel(parent)
        self.window.title("Welcome to Surasura!")
        self.window.geometry("500x620")
        self.window.resizable(False, False)
        self.window.configure(bg=BG_COLOR)
        self.window.transient(parent) # Stay on top of parent
        self.window.grab_set() # Modal
        
        self.on_complete_callback = on_complete_callback
        
        # Set Icon
        try:
            icon_path = get_icon_path()
            if os.path.exists(icon_path):
                self.icon_photo = tk.PhotoImage(file=icon_path)
                self.window.iconphoto(False, self.icon_photo)
        except Exception:
            pass

        self.setup_ui()
        
        # Center window
        self.window.update_idletasks()
        width = self.window.winfo_width()
        height = self.window.winfo_height()
        x = (self.window.winfo_screenwidth() // 2) - (width // 2)
        y = (self.window.winfo_screenheight() // 2) - (height // 2)
        self.window.geometry(f'+{x}+{y}')

    def setup_ui(self):
        main_frame = tk.Frame(self.window, bg=BG_COLOR, padx=30, pady=30)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Welcome Title
        title_label = tk.Label(main_frame, text="Welcome to Surasura (スラスラ)!", 
                              font=("Segoe UI", 18, "bold"), fg=SECONDARY_COLOR, bg=BG_COLOR)
        title_label.pack(pady=(0, 20))

        # Language Selection
        lang_frame = tk.Frame(main_frame, bg=BG_COLOR)
        lang_frame.pack(pady=(0, 20))
        
        tk.Label(lang_frame, text="Target Language:", font=("Segoe UI", 11, "bold"), 
                 fg=TEXT_COLOR, bg=BG_COLOR).pack(side=tk.LEFT, padx=(0, 10))
                 
        self.language_var = tk.StringVar(value="ja")
        
        style = ttk.Style()
        style.configure("TRadiobutton", background=BG_COLOR, foreground=TEXT_COLOR, font=("Segoe UI", 10))
        
        ttk.Radiobutton(lang_frame, text="Japanese (日本語)", variable=self.language_var, value="ja").pack(side=tk.LEFT, padx=(0, 15))
        ttk.Radiobutton(lang_frame, text="Chinese (中文)", variable=self.language_var, value="zh").pack(side=tk.LEFT)

        # Core Philosophy
        philosophy_frame = tk.Frame(main_frame, bg=SURFACE_COLOR, padx=15, pady=15)
        philosophy_frame.pack(fill=tk.X, pady=(0, 20))
        
        philosophy_text = "The only Frequency List that matters\nis the one based on your immersion"
        philosophy_label = tk.Label(philosophy_frame, text=philosophy_text, 
                                   font=("Segoe UI", 11, "bold italic"), fg=ACCENT_COLOR, 
                                   bg=SURFACE_COLOR, justify=tk.CENTER)
        philosophy_label.pack()

        intro_text = "Surasura makes that for you, and helps you study it in the most effective order possible."
        intro_label = tk.Label(main_frame, text=intro_text, font=("Segoe UI", 10), 
                              fg=TEXT_COLOR, bg=BG_COLOR, justify=tk.CENTER, wraplength=440)
        intro_label.pack(pady=(0, 25))

        # How it works
        how_title = tk.Label(main_frame, text="How does it work?", 
                            font=("Segoe UI", 12, "bold"), fg=SECONDARY_COLOR, bg=BG_COLOR)
        how_title.pack(anchor=tk.W, pady=(0, 10))

        step1_frame = tk.Frame(main_frame, bg=BG_COLOR)
        step1_frame.pack(anchor=tk.W, fill=tk.X, pady=(0, 5))
        
        tk.Label(step1_frame, text="→ Upload Immersion content", font=("Segoe UI", 11), 
                 fg=TEXT_COLOR, bg=BG_COLOR).pack(side=tk.LEFT)
        tk.Label(step1_frame, text="(subtitles, EPUBs, Anki decks, Books)", 
                 font=("Segoe UI", 9, "italic"), fg="#888", bg=BG_COLOR).pack(side=tk.LEFT, padx=(5, 0))

        tk.Label(main_frame, text="→ Add your Known-Words List", font=("Segoe UI", 11), 
                 fg=TEXT_COLOR, bg=BG_COLOR).pack(anchor=tk.W, pady=(0, 15))

        tk.Label(main_frame, text="Then learn ONLY the words you'll actually see in your immersion.", 
                 font=("Segoe UI", 10, "bold"), fg=ACCENT_COLOR, bg=BG_COLOR, justify=tk.LEFT, wraplength=440)
        tk.Label(main_frame, text="", bg=BG_COLOR).pack() # Spacer

        # Why section
        why_title = tk.Label(main_frame, text="Why?", font=("Segoe UI", 11, "italic"), 
                            fg="#aaa", bg=BG_COLOR)
        why_title.pack(anchor=tk.W, pady=(10, 5))

        why_text = "I was tired of learning words I never see, and I also like reading physical books.\n\nLearn words chapter by chapter, episode by episode with a スラスラ Vocabulary Journey!"
        tk.Label(main_frame, text=why_text, font=("Segoe UI", 10, "italic"), 
                 fg="#aaa", bg=BG_COLOR, justify=tk.LEFT, wraplength=440).pack(anchor=tk.W)

        # Footer Button
        btn_frame = tk.Frame(main_frame, bg=BG_COLOR)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(20, 0))

        # Style the button using ttk for better looks
        style = ttk.Style()
        style.configure("Onboard.TButton", font=("Segoe UI", 11, "bold"), padding=10)
        
        confirm_btn = ttk.Button(btn_frame, text="Let's Start!", style="Onboard.TButton", 
                                command=self.complete)
        confirm_btn.pack(fill=tk.X)

    def complete(self):
        # Save Language Code
        try:
            settings_path = get_user_file("settings.json")
            settings = {}
            if os.path.exists(settings_path):
                with open(settings_path, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
            
            settings["target_language"] = self.language_var.get()
            
            with open(settings_path, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=4)
        except Exception as e:
            print(f"Error saving settings: {e}")

        if self.on_complete_callback:
            self.on_complete_callback()
        self.window.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()
    OnboardingGuide(root, lambda: print("Complete"))
    root.mainloop()
