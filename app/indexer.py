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
        from app.zh_script import effective

        files = _content_files(get_data_path(language))

        # Must match the tokenizer identity a Generate run uses, or the two would fight over the
        # store (each rebuilding the other's tokens). The GUI passes --reinforce and --zh-script to
        # the analyzer for zh from these settings; mirror that here.
        settings = settings_manager.load_settings()
        reinforce = bool(settings.get("reinforce_segmentation", False))
        script = effective(language, settings.get("zh_script", "asis"))

        store = token_index.open_store(language)
        try:
            # Delta reconcile: only changed/new files are tokenized; removed files are dropped.
            store.reconcile(files, token_index.make_tokenizer(language, reinforce=reinforce, script=script),
                            build_signature=token_index.build_signature(language, reinforce, script))

            # Refresh the tokenizer-normalized known-words cache if KnownWord.json changed (edit,
            # delete, or new). Makes the preview's known-filter EXACT (not the GUI's dictForm approx).
            known_file = os.path.join(get_user_files_path(language), "KnownWord.json")
            sig = token_index.known_signature(known_file, script)
            if store.get_cached_known(sig) is None:
                from app import analyzer
                analyzer.SANITIZE_JA = (language == "ja")
                # The SAME tokenizer a run uses. This used to build ChineseTokenizer() with no
                # reinforce while the analyzer passed it, and both write this one cache entry.
                tok = (analyzer.ChineseTokenizer(reinforce_segmentation=reinforce, script=script)
                       if language == "zh" else analyzer.JapaneseTokenizer())
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
