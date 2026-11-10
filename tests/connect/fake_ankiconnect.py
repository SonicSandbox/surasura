"""A fake AnkiConnect on a loopback port, for ⇄ Swap's tests and its demo (Michi-SW): the real adapter
(`app/anki_connect.py`) talks HTTP to it exactly as to Anki. It holds notes (id -> fields, tags, cards) and a media
folder, answers the actions Swap uses, and records every action in order — with, for each write, whether Swap's undo
file already existed (`on_write(action)`: the snapshot-first check). `reviewing` makes `guiReviewActive` true;
`closed` refuses every request as a closed Anki does (connection refused is the real one; here: a 500 the adapter
reads as an error)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeAnkiConnect:
    def __init__(self, notes=None, on_write=None):
        self.notes = {int(k): v for k, v in (notes or {}).items()}
        self.media = {}
        self.actions = []
        self.reviewing = False
        self.closed = False
        self.refuse_update = None       # an error message: updateNoteFields refused
        self.ignore_update = False      # updateNoteFields answers OK and changes nothing
        self.on_write = on_write or (lambda action: None)
        self.lock = threading.Lock()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                return

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8"))
                if fake.closed:
                    self.send_response(500)
                    self.end_headers()
                    return
                try:
                    reply = {"result": fake.answer(body["action"], body.get("params") or {}), "error": None}
                except Exception as e:      # an action AnkiConnect refuses
                    reply = {"result": None, "error": str(e)}
                data = json.dumps(reply, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d" % self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def names(self):
        return [a for a, _p in self.actions]

    def answer(self, action, params):
        with self.lock:
            self.actions.append((action, params))
            if action == "version":
                return 6
            if action == "guiReviewActive":
                return self.reviewing
            if action == "findNotes":
                return self._find(params["query"])
            if action == "notesInfo":
                return [self._info(n) for n in params["notes"] if int(n) in self.notes]
            if action == "cardsInfo":
                return [{"cardId": c, "note": n, "deckName": note.get("deck", "DevTest")}
                        for c in params["cards"] for n, note in self.notes.items()
                        if c in note.get("cards", [n + 1])]
            if action == "getMediaFilesNames":
                return [n for n in self.media if n == params["pattern"]]
            if action == "storeMediaFile":
                self.on_write(action)
                if params["filename"] in self.media and not params.get("deleteExisting", True):
                    return params["filename"]
                self.media[params["filename"]] = params["data"]
                return params["filename"]
            if action == "updateNoteFields":
                self.on_write(action)
                if self.refuse_update:
                    raise ValueError(self.refuse_update)
                note = self.notes[int(params["note"]["id"])]
                if self.ignore_update:              # (AnkiConnect's known gap: the note open in Anki's editor)
                    return None
                for name, value in params["note"]["fields"].items():
                    if name not in note["fields"]:
                        raise ValueError(f"no field {name}")
                    note["fields"][name] = value
                return None
            if action in ("addTags", "removeTags"):
                self.on_write(action)
                for n in params["notes"]:
                    tags = self.notes[int(n)].setdefault("tags", [])
                    for tag in params["tags"].split():
                        if action == "addTags" and tag not in tags:
                            tags.append(tag)
                        if action == "removeTags" and tag in tags:
                            tags.remove(tag)
                return None
            raise ValueError(f"unsupported action {action}")

    def _info(self, note_id):
        note = self.notes[int(note_id)]
        return {"noteId": int(note_id), "modelName": note.get("model", "Lapis"), "tags": list(note.get("tags", [])),
                "fields": {k: {"value": v, "order": i} for i, (k, v) in enumerate(note["fields"].items())},
                "cards": list(note.get("cards", [int(note_id) + 1]))}

    def _find(self, query):
        """`deck:"D" "Field:value"` as Swap asks it (the value's backslash escapes read back)."""
        import re
        found = re.fullmatch(r'deck:"(.*)" "([^:]+):(.*)"', query)
        if not found:
            raise ValueError(f"query the fake doesn't read: {query}")
        deck, field, value = (re.sub(r'\\(.)', r'\1', g) for g in found.groups())
        return [n for n, note in self.notes.items()
                if note.get("deck", "DevTest") == deck and note["fields"].get(field) == value]
