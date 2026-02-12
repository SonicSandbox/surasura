# Zen Mode (Legacy Documentation)

This document preserves the implementation details of "Zen Mode" (and the "Zen Focus" theme), which was removed in February 2026. This is intended for reference in case the feature needs to be re-implemented or if its minimal design principles are needed for other features.

## Overview
Zen Mode provided a distraction-free, minimal reading experience. It used a monospace font, a black-and-white color palette, and a scroll-focused layout. It also included a "Zen Word Limit" to focus on a small number of high-priority words across all files.

## CSS Styling (`web_app.html`)
The Zen Focus theme was applied via the `theme-zen-focus` class on the `<body>` element.

```css
/* --- THEME: Zen Focus --- */
body.theme-zen-focus {
    --background: #000000;
    --surface: #0a0a0a;
    --card-border: #1a1a1a;
    --primary: #ffffff;
    --secondary: #aaaaaa;
    --text-primary: #dddddd;
    --text-secondary: #666666;
    background-color: var(--background);
    color: var(--text-primary);
    font-family: ui-monospace, 'Cascadia Code', 'Source Code Pro', Menlo, Consolas, monospace;
    overflow-y: auto !important;
    height: auto !important;
    display: block !important;
}

body.theme-zen-focus #content-area,
body.theme-zen-focus .view,
body.theme-zen-focus .progressive-container,
body.theme-zen-focus .word-list-container {
    overflow: visible !important;
    height: auto !important;
    flex: none !important;
    display: block !important;
}

body.theme-zen-focus .word-list-container {
    max-width: 700px;
    margin: 0 auto;
    padding: 40px 20px;
}

body.theme-zen-focus header {
    position: sticky;
    top: 0;
    z-index: 100;
    background-color: rgba(0, 0, 0, 0.9);
    border-bottom: 1px solid var(--card-border);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 0 20px;
}

body.theme-zen-focus header h1 {
    margin: 0;
    padding: 10px 0;
    font-size: 1.2rem;
    opacity: 0.5;
}

body.theme-zen-focus * {
    box-shadow: none !important;
    transition: none !important;
    animation: none !important;
    backdrop-filter: none !important;
}

body.theme-zen-focus .card {
    background-color: transparent;
    border: 1px solid var(--card-border);
    border-radius: 4px;
    padding: 15px;
    margin-bottom: 10px;
}

body.theme-zen-focus .word-main {
    font-size: 1.8rem;
    font-weight: bold;
    color: var(--primary);
}

body.theme-zen-focus .reading {
    color: var(--secondary);
    font-size: 1.2rem;
    margin-left: 12px;
}

body.theme-zen-focus .context-box {
    background: transparent;
    border: none;
    border-left: 1px solid var(--text-secondary);
    padding-left: 10px;
    font-size: 1.2rem;
    display: flex;
    flex-direction: column;
    gap: 12px;
}

body.theme-zen-focus .context-item-zen {
    line-height: 1.5;
}

body.theme-zen-focus .context-box em {
    color: var(--primary);
    font-weight: bold;
    text-decoration: underline;
}
/* ... additional overrides for sidebar and stats ... */
```

## JavaScript Logic (`web_app.html`)
The logic handled conditional rendering for "Zen" mode, which often bypassed the sidebar/tab structure to show all content in a single stream.

```javascript
const isZen = typeof globalTheme !== 'undefined' && globalTheme && globalTheme.toLowerCase() === 'zen focus';

if (isZen) {
    // Render all files as a single stream
    globalData.progressive.forEach(fileData => {
        listContainer.appendChild(createZenFileSection(fileData));
    });
}
```

The `createZenFileSection` function was used to wrap word lists for each file with a title and comprehension bar:

```javascript
function createZenFileSection(fileData) {
    const fileSection = document.createElement('div');
    fileSection.className = 'zen-file-section';
    // ... logic to add title, comprehension bar, and infinite scroll for words ...
    return fileSection;
}
```

## Python Configuration
Python scripts handled the `zen_limit` which was passed to the generator to slice the results.

### `static_html_generator.py`
```python
if theme == "zen-focus":
    print(f"Zen Focus detected: Limiting to first {zen_limit} words across files.")
    df = df.head(zen_limit)
```

### `analyzer.py` / `main.py`
The GUI included a slider for `zen_limit` (range 25-125) which was saved to `settings.json`.

## Removal Reason
Removed as part of a UI cleanup to focus on more robust "Flow" themes (Dark Flow, Midnight Vibrant) that leverage the sidebar navigation more effectively.
