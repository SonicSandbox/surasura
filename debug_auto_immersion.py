import tkinter as tk
from tkinter import ttk
import sys
import os

# Ensure we can import from app
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.immersion_architect_gui import ImmersionArchitectGui

# Dark Theme Constants (Copied from main.py)
BG_COLOR = "#1e1e1e"
SURFACE_COLOR = "#2d2d2d"
TEXT_COLOR = "#e0e0e0"
ACCENT_COLOR = "#bb86fc"

def apply_dark_theme(root):
    style = ttk.Style()
    style.theme_use('default')
    
    root.configure(bg=BG_COLOR)
    
    # Configure common styles
    style.configure(".", background=BG_COLOR, foreground=TEXT_COLOR, fieldbackground=SURFACE_COLOR, font=('Segoe UI', 10))
    style.configure("TFrame", background=BG_COLOR)
    style.configure("TLabelframe", background=BG_COLOR, bordercolor=SURFACE_COLOR)
    style.configure("TLabelframe.Label", background=BG_COLOR, foreground=ACCENT_COLOR, font=('Segoe UI', 11, 'bold'))
    style.configure("TLabel", background=BG_COLOR, foreground=TEXT_COLOR)
    style.configure("TButton", background=SURFACE_COLOR, foreground=TEXT_COLOR, borderwidth=0, padding=8)
    style.map("TButton", background=[('active', ACCENT_COLOR)], foreground=[('active', BG_COLOR)])
    style.configure("Action.TButton", font=('Segoe UI', 10, 'bold'))
    
    # Treeview specific
    style.configure("Treeview", background="#2d2d2d", fieldbackground="#2d2d2d", foreground="#e0e0e0", borderwidth=0)
    style.configure("Treeview.Heading", background="#3c3c3c", foreground="#e0e0e0", relief="flat")
    style.map("Treeview.Heading", background=[('active', '#4c4c4c')])

def main():
    print("Launching Immersion Architect with Auto-Start (Dark Mode)...")
    root = tk.Tk()
    root.withdraw() # Hide the tiny root window
    
    # Apply theme to root (and thus children)
    apply_dark_theme(root)

    # Create the window
    app = ImmersionArchitectGui(root)
    
    # Auto-start the simulation after UI renders
    print("Triggering simulation in 500ms...")
    app.after(500, app.start_simulation)
    
    # Wait for the app window to be destroyed (by Esc, Close button, or otherwise)
    app.wait_window()
    
    # Once app is gone, kill the root and exit
    try:
        root.destroy()
    except:
        pass
    sys.exit()

if __name__ == "__main__":
    main()
