"""Connect's loop against stand-ins (P2.4 rows 2.4.2–2.4.4): `FakeSteps` answers everything `runner.Steps` would ask
of Anki, Anki Miner, the store and the list, from a plan; `FakeAnki` is Anki's notes as a JSON file, so a child
process killed mid-way leaves them where a real Anki would (`python -m tests.connect.fake_steps PLAN.json` runs the
loop once in a child, killed where the plan says).

The words are real Japanese ones (an episode's list words, by item); the titles are synthetic. Never a live Anki.
"""
import json
import os
import sys

from app.connect import runner

TAG = "surasura::connect::"
# Real words, by item: what each episode's pick finds (lemma, reading, its line)
WORDS = {
    1: [("上層部", "ジョウソウブ"), ("一生懸命", "イッショウケンメイ"), ("走り出す", "ハシリダス")],
    2: [("一生懸命", "イッショウケンメイ"), ("気配", "ケハイ"), ("溜め息", "タメイキ")],
    3: [("約束", "ヤクソク"), ("勇気", "ユウキ")],
}


class FakeAnki:
    """Anki's notes: {note id: {"word", "tags"}} in a JSON file (kept across a killed process)."""

    def __init__(self, path):
        self.path = path
        if not os.path.exists(path):
            self._save({"next": 1000, "notes": {}})

    def _load(self):
        with open(self.path, encoding="utf-8") as f:
            return json.load(f)

    def _save(self, data):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, self.path)

    def add(self, word, tag):
        data = self._load()
        note_id = data["next"]
        data["next"] += 1
        data["notes"][str(note_id)] = {"word": word, "tags": [tag]}
        self._save(data)
        return note_id

    def notes(self, tag=None):
        out = {int(k): v for k, v in self._load()["notes"].items()}
        return {k: v for k, v in out.items() if tag is None or tag in v["tags"]}

    def words(self):
        return [n["word"] for n in self.notes().values()]


class Killed(SystemExit):
    pass


class FakeSteps:
    """The plan (a dict): `line` {lang: [item ids]} · `queue` {lang: [item ids]} (each queued once, as the inbox
    would) · `words` {item: [(word, reading)]} · `blocked` (a reason, or None) · `verdict` (TIMED / NOT_TIMED) ·
    `videos` {item: path or None} · `profile_at_pick` / `profile_at_mine` · `kill` ("pick" · "fit" · "mine" · "fill" ·
    "order" · "mid-batch:<n>" · "after-mine") · `absent` (a set of "anki-miner" · "backfill" · "junban") · `store_id` ·
    `prepare_error` · `staged` · `store_busy` (the library busy: the top 20 can't be read) · `unknown_status` (a word
    Anki Miner answers with a status it doesn't know: uncertain, no crash, no card) · `fill_needs` (Backfill asks for
    you) · `pick_error` (an item whose pick raises an unexpected error) · `staged_after_pick` (an update staged once a
    pick has run)."""

    def __init__(self, folder, plan=None, child=False):
        self.folder = folder
        self.plan = dict(plan or {})
        self.anki = FakeAnki(os.path.join(folder, "anki.json"))
        self.child = child
        self.log = []
        self.records = []
        self.queued = set()

    def _kill(self, point):
        if self.plan.get("kill") == point:
            if self.child:
                os._exit(9)
            raise Killed(point)

    # --- the run
    def lower_priority(self):
        self.log.append(("lower",))

    def update_staged(self):
        return bool(self.plan.get("staged")) or (bool(self.plan.get("staged_after_pick"))
                                                  and any(e[0] == "pick" for e in self.log))

    def settle(self):
        self.log.append(("settle",))

    def enabled(self):
        """`switched_off`: Connect's switch off (from the start, or once the plan's `switch_off_after` step ran)."""
        after = self.plan.get("switch_off_after")
        return not (self.plan.get("switched_off") or (after and any(e[0] == after for e in self.log)))

    def miner_found(self):
        return "anki-miner" not in (self.plan.get("absent") or ())

    def after_write(self, lang):
        self.log.append(("after_write", lang))

    def tag_names(self, lang, note_ids):
        self.log.append(("tag_names", list(note_ids)))
        if self.plan.get("tag_names_wait"):
            raise runner.Wait(runner.ANKI_CLOSED, resume="filling")

    # --- the library
    def consume(self, lang, ledger):
        for item in (self.plan.get("queue") or {}).get(lang, []):
            if (lang, item) not in self.queued:
                self.queued.add((lang, item))
                with ledger.transaction():
                    ledger.queue(lang, item, "user", None, store_id=self.plan.get("queued_store", "store-1"))
        for lang_, item, words in self.plan.get("level") or []:
            if lang_ == lang and ("level", item) not in self.queued:
                self.queued.add(("level", item))
                with ledger.transaction():
                    ledger.queue_level(lang, item, [tuple(w) for w in words], store_id="store-1")

    def mine_line(self, lang):
        if self.plan.get("store_busy"):
            raise runner.Wait(runner.LIBRARY_BUSY)
        return list((self.plan.get("line") or {}).get(lang, []))

    def store_id(self, lang):
        return self.plan.get("store_id", "store-1")

    def title(self, lang, job):
        return f"Example Show - {job['item_id']:02d}"

    def pairing(self, lang, job):
        return (self.plan.get("pairings") or {}).get(str(job["item_id"]))

    def video(self, lang, job):
        videos = self.plan.get("videos") or {}
        return videos.get(str(job["item_id"]), os.path.join(self.folder, f"episode-{job['item_id']}.mkv"))

    def record(self, lang, job, made, mined_at, batch):
        if self.plan.get("library_busy"):
            raise runner.Wait(runner.LIBRARY_BUSY)
        self.records.append((job["item_id"], dict(made), mined_at is not None))
        self.log.append(("record", job["item_id"]))

    # --- Anki and its tools
    def blocked(self, lang):
        self.log.append(("blocked", lang))
        return self.plan.get("blocked")

    def prepare(self, lang, ledger):
        self.log.append(("prepare", lang))
        error = self.plan.get("prepare_error")
        if error == "needs":
            raise runner.Needs("known-sync", "Sync once from Surasura's Anki window first.")
        if error:
            raise runner.Wait(error)

    def run_dir(self, job):
        return os.path.join(self.folder, "runs", job["tag"])

    def _carded(self):
        return set(self.anki.words())

    def pick(self, lang, job, video):
        self.log.append(("pick", job["item_id"]))
        self._kill("pick")
        if job["item_id"] in (self.plan.get("pick_error") or ()):
            raise KeyError("a pairing row this test broke")
        if job.get("kind") == "level":
            candidates = [tuple(w) for w in job.get("words") or ()]
        else:
            words = self.plan.get("words") or {}
            candidates = [tuple(w) for w in words.get(str(job["item_id"]), WORDS.get(job["item_id"], []))]
        carded = self._carded()
        chosen = [{"word": w, "reading": r, "orth": w, "sent": [w], "line_start": 10.0 + n, "line_end": 12.5 + n,
                   "line_text": f"{w}の台詞", "predicted_class": "word"}
                  for n, (w, r) in enumerate(candidates) if w not in carded]
        return {"words": chosen, "file": f"/library/{job['item_id']}.ja.srt", "subtitle": "/runs/copy.srt",
                "profile": self.plan.get("profile_at_pick", "p1"), "anki_miner": "3.7.0",
                "absent": "anki-miner" in (self.plan.get("absent") or ())}

    def fit(self, lang, job, pairing, video, subtitle):
        self.log.append(("fit", job["item_id"]))
        self._kill("fit")
        verdict = self.plan.get("verdict", "timed")
        return (verdict, "hato", None if verdict == "timed" else "Not timed to its video, so no cards.",
                float(self.plan.get("offset", 0.0)))

    def mine(self, lang, job, picked, words, attempt):
        self.log.append(("mine", job["item_id"], attempt, [w["word"] for w in words]))
        self._kill("mine")
        if "anki-miner" in (self.plan.get("absent") or ()):
            raise runner.Skip("Anki Miner isn't installed")
        if self.plan.get("miner_busy"):
            raise runner.Wait(runner.ANKI_MINER_OPEN)
        if self.plan.get("profile_at_mine", "p1") != picked.get("profile"):
            self.plan["profile_at_pick"] = self.plan.get("profile_at_mine", "p1")     # a re-pick sees the new one
            raise runner.Repick()
        out = []
        crash = self.plan.get("crash_mid_batch")
        for n, w in enumerate(words):
            if self.plan.get("kill") == f"mid-batch:{n}":
                self._kill(f"mid-batch:{n}")
            if crash is not None and n >= crash:
                self.plan["crash_mid_batch"] = None if not self.plan.get("crash_always") else crash
                return {"outcomes": [_unsure(x) for x in words], "app": "3.7.0", "doubt": True}
            if w["word"] in (self.plan.get("unknown_status") or ()):
                out.append(_unsure(w))      # a status Anki Miner's caller doesn't know: no card, no crash
                continue
            note = self.anki.add(w["word"], TAG + job["tag"])
            out.append({"word": w["word"], "reading": w["reading"], "outcome": "made", "note_id": note,
                        "line_start": w["line_start"]})
        self._kill("after-mine")
        return {"outcomes": out, "app": "3.7.0", "doubt": False}

    def by_tag(self, lang, job, picked, words):
        self.log.append(("by_tag", job["item_id"]))
        found = {n["word"]: k for k, n in self.anki.notes(TAG + job["tag"]).items()}
        return [dict(_unsure(w), outcome="made", note_id=found[w["word"]]) if w["word"] in found else _unsure(w)
                for w in words]

    def fill(self, lang, job, note_ids):
        self.log.append(("fill", job["item_id"], list(note_ids)))
        self._kill("fill")
        if self.plan.get("fill_needs"):
            raise runner.Needs("needs-you", "Backfill runs for one deck only: choose one in the Backfill window.")
        if "backfill" in (self.plan.get("absent") or ()):
            raise runner.Skip("backfill absent")

    def order(self, lang, job):
        self.log.append(("order", job["item_id"]))
        self._kill("order")
        if "junban" in (self.plan.get("absent") or ()):
            raise runner.Skip("Junban isn't installed")


def _unsure(w):
    return {"word": w["word"], "reading": w["reading"], "outcome": "uncertain", "note_id": None,
            "line_start": w.get("line_start")}


def main(plan_path):
    """A child run: the plan's folder, its ledger, one `runner.run` (killed where the plan says) -> exit 0."""
    with open(plan_path, encoding="utf-8") as f:
        plan = json.load(f)
    from app.connect.ledger import Ledger
    steps = FakeSteps(plan["folder"], plan, child=True)
    with Ledger(os.path.join(plan["folder"], "ledger.sqlite")) as ledger:
        runner.run({}, plan.get("languages", ["ja"]), steps=steps, ledger=ledger, sleep=lambda s: None,
                   looks=plan.get("looks", 1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
