# GUI Design Guidelines & Requirements

This document outlines the design language and requirements for creating new GUI windows in the Surasura project. All AI agents and developers must adhere to these guidelines to ensure consistency.

## 1. Framework
- **Primary Framework**: Python `tkinter`
- **Widgets**: Use `tkinter.ttk` widgets wherever possible for better styling support.

## 2. Color Palette (Dark Theme)
All new windows must implement the following dark theme by default. 

| Variable | Hex Code | Usage |
| :--- | :--- | :--- |
| `BG_COLOR` | `#1e1e1e` | Main window background |
| `SURFACE_COLOR` | `#2d2d2d` | Frames, panels, secondary backgrounds |
| `TEXT_COLOR` | `#e0e0e0` | Primary text |
| `ACCENT_COLOR` | `#bb86fc` | Focus elements, active logic, highlights |
| `SECONDARY_COLOR` | `#03dac6` | Success messages, info buttons |
| `ERROR_COLOR` | `#cf6679` | Error messages, warnings |

### Implementation Note
- Ensure these colors are applied to `bg`, `fg`, `activebackground`, etc.
- For `ttk` widgets, use `ttk.Style` to configure the theme.

## 3. Mandatory Window Behaviors
### 'Esc' to Close
**Requirement:** All new GUI windows (including `Toplevel` popups and main windows) MUST be closable by pressing the `Esc` key.

**Implementation Pattern:**
```python
def close_window(event=None):
    window.destroy()

window.bind("<Escape>", close_window)
```

## 4. Layout & Styling
- **Padding**: Use consistent padding (e.g., `padx=10, pady=10`) for main containers.
- **Resizable**: Windows should generally be resizable unless specific constraints exist.
- **Fonts**: Use default system fonts (Segoe UI usually on Windows) but ensure readability on dark backgrounds.
- **Icons**: Ensure the window icon is set if applicable (see `app_entry.py` for taskbar icon logic).

## 5. Components
- **Buttons**: Should have clear hover states if possible.
- **Scrollbars**: Should match the dark theme (might need custom styling or hiding native scrollbars on some OSs if they clash).
