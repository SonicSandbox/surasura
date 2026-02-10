from bs4 import BeautifulSoup

html_content = """
<html>
<body>
<p>
日本社会の仕組み
</p>
<p>
突然だが、<ruby>変<rt>へん</rt></ruby>な<ruby>奴<rt>やつ</rt></ruby>がいる。
</p>
<p>
訴えて<ruby>止<rt>や</rt></ruby>まない。
</p>
</body>
</html>
"""

def test_extraction(html, strategy_name):
    print(f"--- Strategy: {strategy_name} ---")
    soup = BeautifulSoup(html, 'html.parser')
    
    # Common Step: Remove Furigana
    for rt in soup.find_all('rt'):
        rt.decompose()
    for rp in soup.find_all('rp'):
        rp.decompose()
        
    if strategy_name == "current":
        # The current implementation
        text = soup.get_text(separator='\n')
        print(ascii(text))
        
    elif strategy_name == "unwrap_ruby":
        # Proposed fix: Unwrap ruby tags
        for tag in soup.find_all(['ruby', 'rb', 'span']):
            tag.unwrap()
        
        text = soup.get_text(separator='\n')
        print(ascii(text))

    elif strategy_name == "block_iteration":
        # Another fix: Iterate blocks
        lines = []
        for tag in soup.find_all(['p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
             lines.append(tag.get_text(separator='').strip())
        print(ascii("\n".join(lines)))

    elif strategy_name == "insert_newlines":
        # Strategy: Insert explicit newlines after blocks, then get_text without separator
        # 1. Un-nest ruby to be safe/clean? No need if separator='' works.
        # But wait, if separator='', 'Text<ruby>K<rt>F</rt></ruby>Text' -> 'TextKText' (good).
        
        # 2. Add newlines to blocks
        # We need to be careful not to double count if div contains p.
        # But inserting "\n" after p:
        # <div><p>Tex</p>\n</div> -> div text is "Tex\n"
        
        # Modify the tree
        for tag in soup.find_all(['p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'br']):
            if tag.name == 'br':
                tag.replace_with('\n')
            else:
                # Append newline at the end of the content of the block
                # OR insert after.
                # If we insert after, get_text on parent will see it.
                tag.append("\n")
                
        text = soup.get_text(separator='')
        print(ascii(text))

print("Original Content:")
print(ascii(html_content.strip()))
print("\n")

test_extraction(html_content, "current")
test_extraction(html_content, "unwrap_ruby")
test_extraction(html_content, "insert_newlines")
