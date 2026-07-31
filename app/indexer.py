"""Background token-store reconciler.

Run as a short-lived SUBPROCESS (via the `index` dispatch) so the GUI never imports the tokenizer
— heavy work stays off the main process, per this codebase's architecture. It reconciles the
delta (changed / new / removed content files) and refreshes the tokenizer-normalized known-words
cache, then exits. Best-effort: it never crashes the app, and it only tokenizes files that changed.

This is what makes the word-selection preview *always fresh* without a full analysis run: the GUI
cheaply detects a delta (stat only), launches this, and re-reads the store when it finishes.
"""

import sys
import os


def _content_files(data_dir):
    # Must match the analyzer's scan exactly, or the store would index files a run never reads (or
    # miss ones it does) — hence the shared CONTENT_EXTENSIONS.
    from app.path_utils import is_content_file
    files = []
    for folder in ("HighPriority", "LowPriority", "GoalContent"):
        base = os.path.join(data_dir, folder)
        if os.path.isdir(base):
            for root, _dirs, names in os.walk(base):
                for name in names:
                    if is_content_file(name):
                        files.append(os.path.join(root, name))
    return files


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Surasura background token indexer")
    parser.add_argument("--language", type=str, default="ja")
    args, _ = parser.parse_known_args()
    language = args.language

    try:
        from app import token_index
        from app import settings_manager
        from app.path_utils import get_data_path, get_user_files_path

        files = _content_files(get_data_path(language))

        # Must match the tokenizer identity a Generate run uses, or the two would fight over the
        # store (each rebuilding the other's tokens). The GUI passes --reinforce to the analyzer for
        # zh when this setting is on; mirror that here.
        reinforce = bool(settings_manager.load_settings().get("reinforce_segmentation", False))

        store = token_index.open_store(language)
        try:
            # Delta reconcile: only changed/new files are tokenized; removed files are dropped.
            store.reconcile(files, token_index.make_tokenizer(language, reinforce=reinforce),
                            build_signature=token_index.build_signature(language, reinforce))

            # Refresh the tokenizer-normalized known-words cache if KnownWord.json changed (edit,
            # delete, or new). Makes the preview's known-filter EXACT (not the GUI's dictForm approx).
            known_file = os.path.join(get_user_files_path(language), "KnownWord.json")
            sig = token_index.known_signature(known_file)
            if store.get_cached_known(sig) is None:
                from app import analyzer
                analyzer.SANITIZE_JA = (language == "ja")
                tok = analyzer.ChineseTokenizer() if language == "zh" else analyzer.JapaneseTokenizer()
                known_tuples, known_lemmas = analyzer.load_known_words(known_file, tok)
                store.set_cached_known(sig, known_tuples, known_lemmas)
        finally:
            store.close()
        print(f"Indexer: reconciled {len(files)} files for '{language}'.")
    except Exception as e:
        # Never fatal — the preview just falls back to 'as of last run'.
        print(f"Indexer: skipped ({e})")


if __name__ == "__main__":
    main()
