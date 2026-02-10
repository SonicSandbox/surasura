
import pytest
from app.analyzer import JapaneseTokenizer, ChineseTokenizer

class TestTokenizerEdgeCases:
    
    @pytest.fixture(autouse=True)
    def setup(self):
        self.ja_tokenizer = JapaneseTokenizer()
        self.zh_tokenizer = ChineseTokenizer()

    def test_ja_empty_string(self):
        tokens = self.ja_tokenizer.tokenize("")
        assert tokens == []

    def test_ja_whitespace_only(self):
        tokens = self.ja_tokenizer.tokenize("   \n  \t ")
        assert tokens == []

    def test_ja_punctuation_only(self):
        # Should not crash, might return empty depending on filter logic
        # Current logic filters "Auxiliary Symbol" etc.
        tokens = self.ja_tokenizer.tokenize("。。。！？") 
        # Verify it returns a list (empty or not)
        assert isinstance(tokens, list)

    def test_ja_mixed_script(self):
        # English mixed with Japanese
        text = "Hello こんにちは World"
        tokens = self.ja_tokenizer.tokenize(text)
        # Should contain "こんにちは" parts
        lemmas = [t[0] for t in tokens]
        # "こんにちは" is often normalized to "今日は" by some dictionaries/tokenizers
        assert "こんにちは" in lemmas or "今日は" in lemmas
        
    def test_ja_emoji(self):
        text = "Hello 😺 World"
        tokens = self.ja_tokenizer.tokenize(text)
        assert isinstance(tokens, list)
        
    def test_zh_empty_string(self):
        tokens = self.zh_tokenizer.tokenize("")
        assert tokens == []

    def test_zh_mixed_script(self):
        # Latin mixed with Chinese
        text = "Hello 你好 World"
        tokens = self.zh_tokenizer.tokenize(text)
        lemmas = [t[0] for t in tokens]
        assert "你好" in lemmas
        
    def test_zh_punctuation(self):
        text = "你好，世界。"
        tokens = self.zh_tokenizer.tokenize(text)
        lemmas = [t[0] for t in tokens]
        # Punctuation might be filtered
        assert "你好" in lemmas
        assert "世界" in lemmas
