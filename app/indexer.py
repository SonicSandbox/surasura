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

from app.batch_gc import without_cycle_collection


def _content_files(data_dir, language=None):
    # Must match the analyzer's list exactly, or the store would index files a run never reads (or
    # miss ones it does). With a library store (or its read-only copy) that IS the analyzer's list
    # (Library_Store_Spec K2): a file Graduate left in its tier folder is no longer in it, and indexing it
    # would only be undone by the next run's reconcile. Without one, the walk with the shared
    # CONTENT_EXTENSIONS, as before.
    if language:
        try:
            from app import library_store
            mode, _reason = library_store.check_mode(language, data_dir, busy_wait=0.0)
        except Exception:
            mode = "json"
        if mode in ("store", "read-only"):
            from app.analyzer import resolve_found_files
            return [path for path, _label, _weight, _type in resolve_found_files(language, verbose=False)]
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


def token_store_lists(language, data_dir, files):
    """The token store's two lists (L2.2 05 §5.10, 9b) for `files`, the run's list (`_content_files`, Generate's
    found files): (counted, {"kept", "elsewhere", "forgotten"}) — `Store.reconcile(counted, ..., **more)`, and
    `needs_reconcile`. With a ready library store: counted = `files` as given, then the store's counted items they lack
    (a missing item keeps counting until the user decides); kept = `text_lists()`' kept list (Finished, New arrivals,
    removed items whose text wasn't forgotten); elsewhere = {a removed item's path: where its file is in the trash};
    forgotten = the removed items whose sentences the user forgot. Absolute paths under `data_dir`. Without one (JSON
    mode, read-only, busy, an error): (`files`, {}) — the kept rows and their text left as they are."""
    try:
        from app import library_store
        from app.path_utils import get_user_files_path
        if library_store.check_mode(language, data_dir, busy_wait=0.0)[0] != "store":
            return files, {}
        store = library_store.open_store(language, data_dir, get_user_files_path(language), role="reader",
                                         busy_wait=0.0)
        if store is None:
            return files, {}
        with store:
            counted_rel, kept_rel = store.text_lists()
            trashed, forgotten = store.text_elsewhere(), store.text_forgotten()
    except Exception:
        return files, {}

    def full(rel):
        return os.path.join(data_dir, *(rel[2:] if rel.startswith("./") else rel).split("/"))

    from app.token_index import _norm
    seen = {_norm(p) for p in files}
    counted = list(files)
    for rel in counted_rel:
        path = full(rel)
        if _norm(path) not in seen:
            seen.add(_norm(path))
            counted.append(path)
    return counted, {"kept": [full(rel) for rel in kept_rel],
                     "elsewhere": {full(rel): full(where) for rel, where in trashed.items()},
                     "forgotten": [full(rel) for rel in forgotten]}


def _holding_indexer(run):
    """Run `run` holding the `indexer` lock (`app/locks.py`): informative — `surasura-cli status` reports the indexer
    busy while it is held (P0.3 03) — and one index run at a time per install: a second waits for the first, then
    reconciles whatever the first did not see."""
    import functools

    @functools.wraps(run)
    def wrapper(*args, **kwargs):
        held = None
        try:
            from app import locks
            held = locks.take("indexer", "indexing", wait=None)
        except Exception as e:
            print(f"Indexer: its lock can't be used ({e}); indexing without it.")
        try:
            return run(*args, **kwargs)
        finally:
            if held is not None:
                held.release()
    return wrapper


@without_cycle_collection
@_holding_indexer
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

        data_dir = get_data_path(language)
        files, more = token_store_lists(language, data_dir, _content_files(data_dir, language))

        # Must match the tokenizer identity a Generate run uses, or the two would fight over the
        # store (each rebuilding the other's tokens). The GUI passes --reinforce and --zh-script to
        # the analyzer for zh from these settings; mirror that here.
        settings = settings_manager.load_settings()
        reinforce = bool(settings.get("reinforce_segmentation", False))
        script = effective(language, settings.get("zh_script", "asis"))

        store = token_index.open_store(language)
        try:
            # Delta reconcile: only changed/new files are tokenized; a file in neither list is dropped, a kept one's
            # text kept (its own file) and never counted.
            store.reconcile(files, token_index.make_tokenizer(language, reinforce=reinforce, script=script),
                            build_signature=token_index.build_signature(language, reinforce, script),
                            data_dir=data_dir, **more)
            if language == "ja":
                # The library's name tables the reconcile just computed: the known words read with them.
                from app import names
                names.use_library_tables(store.names_tables())

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
