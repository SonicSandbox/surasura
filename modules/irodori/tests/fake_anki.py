# SPDX-License-Identifier: GPL-3.0-or-later
"""A patched `urlopen` standing in for AnkiConnect (never a live Anki): notes {id: {field: value}}, tags and a media
folder, each request recorded with whether the calling thread held the Anki-write lock then."""
import json
import urllib.error
from unittest import mock

from app import anki_connect, locks

# Real Lapis-shaped notes (everyday sentences and Test Resources/ja's 杜子春), the fields as Anki holds them
NOTES = {
    101: {"Sentence": "彼は毎日<b>冒険</b>に出かけます。", "SentenceAudio": ""},
    102: {"Sentence": "冒険の<b>準備</b>はできていますか？", "SentenceAudio": "[sound:sl-3f9a1c2b7d4e5f60.mp3]"},  # a recorded clip
    103: {"Sentence": "唐の都洛陽の西の門の下に、ぼんやり空を<b>仰いで</b>ゐる、一人の若者がありました。",
          "SentenceAudio": "<br>"},                                                     # holds something
    104: {"Sentence": "素晴らしい冒険が<b>待って</b>いるはずだ。", "SentenceAudio": ""},
    105: {"Sentence": "或春の<b>日暮</b>です。", "SentenceAudio": "ナレーター"},              # text: kept
    106: {"Sentence": "冒険は危険だが、価値がある。", "SentenceAudio": "  \n"},             # spaces: kept (the writer's rule)
}
WRITES = {"storeMediaFile", "updateNoteFields", "addTags", "removeTags", "deleteMediaFile"}


class FakeAnki:
    def __init__(self, notes=None):
        self.notes = {int(k): dict(v) for k, v in (notes if notes is not None else NOTES).items()}
        self.tags = {n: set() for n in self.notes}
        self.media = {}
        self.requests = []
        self.reviewing = False
        self.offline = False
        self.found = None                       # findNotes' answer (None: every note)

    def _one(self, action, params):
        if action == "requestPermission":
            return {"permission": "granted", "version": 6}
        if action == "apiReflect":
            return {"actions": list(params.get("actions") or [])}
        if action == "guiReviewActive":
            return self.reviewing
        if action == "findNotes":
            self.query = params.get("query")
            named = [n for n, f in self.notes.items() if "surasura-sa-" in self.query and
                     any(name in v for v in f.values() for name in self.media if name in self.query)]
            if "surasura-sa-" in self.query:            # the shared writer's look for a clip's users
                return named
            return list(self.notes) if self.found is None else list(self.found)
        if action == "notesInfo":
            return [{"noteId": n, "modelName": "Lapis", "tags": sorted(self.tags[n]),
                     "fields": {k: {"value": v, "order": i} for i, (k, v) in enumerate(self.notes[n].items())}}
                    for n in params["notes"] if n in self.notes]
        if action == "storeMediaFile":
            self.media[params["filename"]] = params["data"]
            return params["filename"]
        if action == "deleteMediaFile":
            self.media.pop(params["filename"], None)
            return None
        if action == "updateNoteFields":
            note = params["note"]
            for k, v in note["fields"].items():
                if k in self.notes[note["id"]]:
                    self.notes[note["id"]][k] = v
            return None
        if action == "addTags":
            for n in params["notes"]:
                self.tags[n].add(params["tags"])
            return None
        if action == "removeTags":
            for n in params["notes"]:
                self.tags[n].discard(params["tags"])
            return None
        raise ValueError(f"unknown action {action}")

    def __call__(self, request, timeout=None):
        payload = json.loads(request.data.decode("utf-8"))
        action, params = payload["action"], payload.get("params") or {}
        self.requests.append((action, params, locks.held_here(anki_connect.WRITER_LOCK)))
        if self.offline:
            raise urllib.error.URLError(ConnectionRefusedError(10061, "refused"))
        if action == "multi":
            out = []
            for sub in params["actions"]:
                self.requests.append((sub["action"], sub.get("params") or {},
                                      locks.held_here(anki_connect.WRITER_LOCK)))
                try:
                    out.append({"result": self._one(sub["action"], sub.get("params") or {}), "error": None})
                except ValueError as e:
                    out.append({"result": None, "error": str(e)})
            result, error = out, None
        else:
            try:
                result, error = self._one(action, params), None
            except ValueError as e:
                result, error = None, str(e)
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {"result": result, "error": error}, ensure_ascii=False).encode("utf-8")
        return response

    def sent(self, action):
        return [params for a, params, _held in self.requests if a == action]
