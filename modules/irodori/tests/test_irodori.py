# SPDX-License-Identifier: GPL-3.0-or-later
"""The AI voice's beta (modules/irodori): its contract, the K2 caption, the install's checks, the server, the
run, Connect's queue, and the seam to the shared writer.

What a wrong answer would cost, in order:
  * a card's recorded audio written over, or AI audio made for a card that has some (the run asks only for the empty);
  * a second writer: anything written but through the seam to the shared writer;
  * a download used that isn't the pinned one (a hash not checked), or a half install read as installed;
  * *Remove* deleting a folder the installer didn't make;
  * a run stopped half-way that loses what it made, or a Connect queue that holds a part back.
"""
import hashlib
import io
import json
import os
import subprocess
import sys
import threading
import zipfile
from unittest import mock

import pytest

import modules.irodori as irodori
from app import anki_connect
from modules.irodori import make, queue, runtime, server, voice, writer
from modules.irodori.tests.fake_anki import WRITES, FakeAnki

URL = anki_connect.DEFAULT_URL
WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 200
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


@pytest.fixture
def anki():
    fake = FakeAnki()
    with mock.patch("urllib.request.urlopen", fake):
        yield fake


# --- the contract -------------------------------------------------------------------------------------------------- #
def test_the_beta_is_off_by_default(installed, shared_writer):
    assert irodori.SETTINGS_DEFAULTS["enable_irodori"] is False
    assert not irodori.on(dict(irodori.SETTINGS_DEFAULTS))
    assert irodori.on({"enable_irodori": True})


def test_on_needs_the_voice_installed(shared_writer):
    assert not irodori.on({"enable_irodori": True})


def test_on_is_japanese_only(installed, shared_writer):
    assert irodori.on({"enable_irodori": True}, "ja") and not irodori.on({"enable_irodori": True}, "zh")


def test_a_writer_whose_contract_changed_is_never_used(installed, monkeypatch):
    # why: the seam is written to the shared writer's two calls; if they change shape AI audio turns off, never on
    import types
    fake = types.ModuleType("app.connect.sentence_audio")
    fake.fill = lambda anki, ledger, clips, field="SentenceAudio", tag="t": pytest.fail("called")    # no `by`
    fake.undo = lambda anki, ledger, rid: pytest.fail("called")
    fake.record = lambda ledger, rid: None
    fake.Reviewing, fake.AnkiConnectNotes = type("Reviewing", (Exception,), {}), type("AnkiConnectNotes", (), {})
    import app.connect
    monkeypatch.setitem(sys.modules, "app.connect.sentence_audio", fake)
    monkeypatch.setattr(app.connect, "sentence_audio", fake, raising=False)
    assert not writer.available() and not irodori.on({"enable_irodori": True})
    fake.fill = lambda anki, ledger, clips, field="SentenceAudio", tag="t", by="x", texts=None, verb="v": None
    assert not writer.available(), "undo still the old shape"
    fake.undo = lambda anki, ledger, rid, verb="v": None
    assert writer.available()


def test_the_real_shared_writer_honours_the_seams_contract():
    from app.connect import sentence_audio
    assert writer._shared() is sentence_audio


def test_on_needs_the_shared_writer_and_without_it_nothing_is_offered(installed, monkeypatch):
    # why: one writer — without the shared one, no door may offer AI audio
    monkeypatch.setattr(writer, "_shared", lambda: None)
    assert not irodori.on({"enable_irodori": True})
    got = writer.fill(URL, "ja", {101: __file__}, tag=writer.AI_TAG)
    assert not got["ok"] and got["waits"] and got["problems"] == [writer.WAITS]


def test_no_setting_holds_a_credential_or_a_path():
    for key, value in irodori.SETTINGS_DEFAULTS.items():
        assert "key" not in key.lower() and "token" not in key.lower()
        assert not (isinstance(value, str) and (":" in value or "\\" in value))


def test_importing_the_package_imports_nothing_heavy():
    code = ("import sys; import modules.irodori; "
            "print([m for m in ('PyQt6', 'modules.irodori.make', 'modules.irodori.server', 'app.anki_connect') "
            "if m in sys.modules])")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=_REPO)
    assert out.stdout.strip() == "[]", out.stderr


def test_only_the_seam_and_the_count_name_anki_writes():
    # why: one writer — no file of the module sends a write action to Anki itself; the seam forwards to the shared one
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in os.listdir(here):
        if name.endswith(".py"):
            src = open(os.path.join(here, name), encoding="utf-8").read()
            for action in WRITES:
                assert f'"{action}"' not in src, (name, action)


# --- the K2 caption ------------------------------------------------------------------------------------------------ #
@pytest.mark.parametrize("line, who", [
    ("おい、待てよ！俺も行くぜ。", "male"), ("僕はそれでいいと思う。", "male"), ("そんなの知らねえよ、だろ？", "male"),
    ("あら、素敵な帽子ね。どこで買ったのかしら？", "female"), ("あたしのせいじゃないわよ。", "female"),
    ("彼は毎日冒険に出かけます。", "female"),                                          # nothing says: a woman (K2)
    ("唐の都洛陽の西の門の下に、ぼんやり空を仰いでゐる、一人の若者がありました。", "female")])
def test_who_says_the_line_is_read_from_its_own_words(line, who):
    assert voice.speaker(line) == who


@pytest.mark.parametrize("line, how", [("冒険の準備はできていますか？", "ask"), ("冒険する？", "ask"),
                                       ("少し待ってください。", "request"), ("冒険！", "exclaim"),
                                       ("冒険は危険だが、価値がある。", "tell")])
def test_how_the_line_is_said(line, how):
    assert voice.delivery(line) == how


def test_every_caption_of_the_shipped_pack_is_short_natural_and_never_says_a_banned_word(ja_sentences):
    pack = voice.pack()
    assert pack["id"] == voice.DEFAULT and pack["speed"] == 1.1 and pack["voice"] == "none" and not pack["lora"]
    lines = ja_sentences + ["おい、待てよ！俺も行くぜ。", "あら、素敵な帽子ね。どこで買ったのかしら？", "少し待ってください。"]
    seen = set()
    for line in lines:
        cap = voice.caption(line, pack)
        seen.add(cap)
        assert len(cap) <= voice.MAX_CAPTION
        assert "自然な声" in cap and "ふつうの速さ" in cap
        assert not [w for w in voice.BANNED if w in cap], cap
    assert len(seen) >= 4                     # a man / a woman; telling / asking / asking for / exclaiming


def test_the_same_sentence_always_gets_the_same_seed():
    assert voice.seed("冒険だ。") == voice.seed("冒険だ。") != voice.seed("冒険する？")


@pytest.mark.parametrize("field, text", [
    ("彼は毎日<b>冒険</b>に出かけます。", "彼は毎日冒険に出かけます。"),
    ("<ruby>冒険<rt>ぼうけん</rt></ruby>の準備", "冒険の準備"),
    ("冒険[ぼうけん]の 準備[じゅんび]はできていますか？", "冒険の準備はできていますか？"),
    ("今夜は{{c1::冒険}}。[sound:sl-ab.mp3]", "今夜は冒険。"),
    ("冒険は危険だが、<br>価値がある。&amp;", "冒険は危険だが、 価値がある。&"),
])
def test_the_sentence_field_is_read_as_the_voice_should_say_it(field, text):
    assert voice.sentence_text(field) == text


def test_a_line_with_no_japanese_or_too_long_is_skipped_never_cut():
    assert voice.usable("Hello there.") == "no Japanese"
    assert voice.usable("我们明天去冒险吧。") == "no Japanese"          # Chinese: no kana, never the Japanese voice
    assert voice.usable("あ" * (voice.MAX_CHARS + 1)) == "too long"
    assert voice.usable("冒険だ。") is None


def test_a_pack_added_later_replaces_the_shipped_one_only_with_a_higher_version(tmp_path):
    folder = tmp_path / "voices"
    folder.mkdir()
    base = dict(voice.pack(), name="A fine-tuned voice", lora="loras/my-voice.safetensors")
    (folder / "same.json").write_text(json.dumps(dict(base, version=1)), encoding="utf-8")
    assert voice.pack(runtime_home=str(tmp_path))["name"] == "Natural speech (K2)"
    (folder / "same.json").write_text(json.dumps(dict(base, version=2)), encoding="utf-8")
    assert voice.pack(runtime_home=str(tmp_path))["lora"] == "loras/my-voice.safetensors"
    (folder / "broken.json").write_text("{", encoding="utf-8")
    assert voice.pack("gone", runtime_home=str(tmp_path))["id"] == voice.DEFAULT


def test_a_pack_with_no_captions_sends_none():
    assert voice.caption("冒険だ。", dict(voice.pack(), captions=None)) is None


# --- the backend and the install ------------------------------------------------------------------------------------ #
def _smi(text, code=0):
    return lambda *a, **k: mock.Mock(returncode=code, stdout=text)


@pytest.mark.parametrize("smi, want", [
    ("NVIDIA GeForce GTX 1060 3GB, 3072, 560.94, 6.1", "cpu"),          # 3 GB: spills, slower than the CPU
    ("NVIDIA GeForce GTX 1080, 8192, 470.256, 6.1", "cpu"),             # a driver under 525
    ("NVIDIA GeForce GTX 1080, 8192, 560.94, 6.1", "cu126"),
    ("NVIDIA GeForce RTX 4080, 16376, 581.15, 8.9", "cu126"),
    ("NVIDIA GeForce RTX 5070, 12227, 581.15, 12.0", "cu128"),
    ("NVIDIA GeForce GTX 1060 3GB, 3072, 560.94, 6.1\nNVIDIA GeForce RTX 4080, 16376, 581.15, 8.9", "cu126"),
])
def test_the_gpu_is_used_only_when_it_can_hold_the_model(smi, want):
    assert runtime.backend(runtime.gpu(run=_smi(smi))) == want


def test_no_nvidia_smi_or_a_failing_one_means_the_cpu():
    def missing(*a, **k):
        raise FileNotFoundError("nvidia-smi")
    assert runtime.gpu(run=missing) is None and runtime.backend(None) == "cpu"
    assert runtime.gpu(run=_smi("", code=9)) is None


class FakeNet:
    """Every URL the install fetches -> its bytes. Records what was asked."""

    def __init__(self, files):
        self.files, self.asked = files, []

    def __call__(self, req, timeout=None):
        url = getattr(req, "full_url", req)
        self.asked.append(url)
        if url not in self.files:
            raise OSError("not found")
        return io.BytesIO(self.files[url])


def _pins(monkeypatch):
    """The pins patched to small stand-in files, each with its right hash -> the FakeNet serving them."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("uv-x86_64-pc-windows-msvc/uv.exe", b"MZ fake uv")
    files = {runtime.UV["url"]: buf.getvalue()}
    monkeypatch.setitem(runtime.UV, "sha256", hashlib.sha256(buf.getvalue()).hexdigest())
    models, marks = [], []
    for repo, rev, path, _size, _h in runtime.MODEL_FILES:
        data = f"{repo}/{path}".encode()
        files[runtime.HF.format(repo=repo, rev=rev, path=path)] = data
        models.append((repo, rev, path, len(data), "sha256:" + hashlib.sha256(data).hexdigest()))
    for path, _size, _h in runtime.WATERMARK_FILES:
        data = f"wm/{path}".encode()
        files[runtime.HF.format(repo=runtime.WATERMARK_REPO, rev=runtime.WATERMARK_REV, path=path)] = data
        marks.append((path, len(data), "git:" + hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()))
    monkeypatch.setattr(runtime, "MODEL_FILES", tuple(models))
    monkeypatch.setattr(runtime, "WATERMARK_FILES", tuple(marks))
    return FakeNet(files)


class FakeUv:
    """uv: `venv` makes env/Scripts/python.exe; `pip install` succeeds (or fails on `fail_on`). Records the commands."""

    def __init__(self, fail_on=None):
        self.commands, self.fail_on = [], fail_on

    def __call__(self, cmd, **kw):
        self.commands.append(cmd)
        code = 1 if self.fail_on and self.fail_on in " ".join(cmd) else 0
        if "venv" in cmd and not code:
            os.makedirs(os.path.join(cmd[-1], "Scripts"), exist_ok=True)
            open(os.path.join(cmd[-1], "Scripts", "python.exe"), "wb").close()
        proc = mock.Mock(returncode=code)
        proc.communicate = mock.Mock(return_value=(b"error: something failed" if code else b"", None))
        return proc


def test_the_install_fetches_every_pinned_file_checked_and_marks_installed_last(monkeypatch):
    net, uv = _pins(monkeypatch), FakeUv()
    steps = []
    got = runtime.install(say=lambda s, n, t: steps.append(s), chosen="cpu", opener=net, run=uv)
    assert got["installed"] and got["backend"] == "cpu"
    assert steps == [1, 2, 3, 4, 5, 6]
    joined = [" ".join(c) for c in uv.commands]
    assert any("venv --python 3.10.22 --managed-python" in c for c in joined)
    assert any("--require-hashes -r" in c and "requirements-torch-cpu.txt" in c and
               "--index-url https://download.pytorch.org/whl/cpu" in c for c in joined)
    assert any("--no-deps --require-hashes -r" in c and c.endswith("requirements-server.txt") for c in joined)
    assert any("Irodori-TTS-Server/archive/61012c7" in c and "silentcipher/archive/d46d7d0" in c for c in joined)
    assert all("--no-deps" in c for c in joined if " pip install " in c)
    assert os.path.isfile(os.path.join(runtime.hf_home(), "hub", "models--sony--silentcipher", "refs", "main"))
    for url in net.asked:                     # every URL asked is a pinned one
        assert url.startswith("https://github.com/astral-sh/uv/releases/download/0.13.4/") or \
            (url.startswith("https://huggingface.co/") and "/resolve/" in url and "/resolve/main/" not in url)


def _requirements(name):
    """A requirement file's entries, each with its --hash lines -> [(name==version, [hashes])]."""
    text = open(os.path.join(os.path.dirname(runtime.__file__), name), encoding="utf-8").read()
    entries = []
    for line in text.splitlines():
        line = line.strip().rstrip(chr(92)).strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("--hash="):
            entries[-1][1].append(line)
        else:
            entries.append((line, []))
    return entries


def test_every_server_and_cpu_torch_package_is_pinned_and_hashed_and_none_is_a_git_url():
    server = _requirements("requirements-server.txt")
    torch = _requirements("requirements-torch-cpu.txt")
    assert len(server) > 100 and [n for n, _h in torch] == ["torch==2.10.0+cpu", "torchaudio==2.10.0+cpu"]
    for name, hashes in server + torch:
        assert "==" in name and "git+" not in name and hashes, name
    assert not [n for n, _h in server if n.split("==")[0] in ("torch", "torchaudio")]
    assert len(runtime.ARCHIVES) == 4 and all("/archive/" in a and a.endswith(".zip") for a in runtime.ARCHIVES)


def test_a_file_that_doesnt_match_its_hash_is_thrown_away_and_nothing_reads_installed(monkeypatch):
    net = _pins(monkeypatch)
    repo, rev, path, _s, _h = runtime.MODEL_FILES[0]
    net.files[runtime.HF.format(repo=repo, rev=rev, path=path)] = b"a different model!"
    with pytest.raises(runtime.InstallError, match="didn't match"):
        runtime.install(chosen="cpu", opener=net, run=FakeUv())
    assert not runtime.status()["installed"]
    assert not os.path.exists(runtime.model_path()) and not os.path.exists(runtime.model_path() + ".part")


def test_a_failed_uv_step_says_why_and_leaves_it_not_installed(monkeypatch):
    with pytest.raises(runtime.InstallError, match="something failed"):
        runtime.install(chosen="cpu", opener=_pins(monkeypatch), run=FakeUv(fail_on="torch"))
    assert not runtime.status()["installed"]


def test_offline_says_to_check_the_connection():
    def offline(*a, **k):
        raise OSError("getaddrinfo failed")
    with pytest.raises(runtime.InstallError, match="internet connection"):
        runtime.install(chosen="cpu", opener=offline, run=FakeUv())


def test_cancel_stops_it_and_the_next_install_picks_up_after(monkeypatch):
    net, cancel = _pins(monkeypatch), threading.Event()

    def say(step, of, text):
        if step == 3:
            cancel.set()
    with pytest.raises(runtime.Cancelled):
        runtime.install(say=say, cancel=cancel, chosen="cpu", opener=net, run=FakeUv())
    assert not runtime.status()["installed"]
    asked = len(net.asked)
    assert runtime.install(chosen="cpu", opener=net, run=FakeUv())["installed"]
    assert runtime.UV["url"] not in net.asked[asked:]          # the installer kept from the first try


def test_a_reinstall_never_reads_installed_while_it_runs(installed, monkeypatch):
    net, seen = _pins(monkeypatch), []
    runtime.install(say=lambda s, n, t: seen.append(runtime.status()["installed"]), chosen="cpu", opener=net,
                    run=FakeUv())
    assert seen and not any(seen)


def test_remove_deletes_only_the_folder_the_installer_made(installed):
    assert runtime.remove() >= 0 and not os.path.exists(installed)


def test_remove_refuses_while_a_run_holds_the_voice(installed):
    from app import path_utils
    held = runtime.running()
    try:
        with pytest.raises(runtime.InstallError, match="making audio now"):
            runtime.remove()
    finally:
        path_utils.release_lock(held)
    assert runtime.status()["installed"]
    assert runtime.remove() >= 0 and not os.path.exists(installed)


def test_a_remove_that_fails_part_way_keeps_the_mark_so_remove_can_run_again(installed, monkeypatch):
    real = os.remove

    def locked(path):
        if str(path).endswith("installed.json"):
            raise PermissionError("in use")
        return real(path)
    monkeypatch.setattr(runtime.os, "remove", locked)
    with pytest.raises(runtime.InstallError, match="still in use"):
        runtime.remove()
    assert os.path.isfile(os.path.join(installed, runtime.MARKER))
    monkeypatch.setattr(runtime.os, "remove", real)
    runtime.remove()
    assert not os.path.exists(installed)


def test_install_refuses_a_folder_that_holds_other_files(tmp_path, monkeypatch):
    other = tmp_path / "Documents"
    other.mkdir()
    (other / "日記.txt").write_text("冒険", encoding="utf-8")
    monkeypatch.setenv("SURASURA_IRODORI_HOME", str(other))
    with pytest.raises(runtime.InstallError, match="other files"):
        runtime.install(chosen="cpu", opener=lambda *a, **k: pytest.fail("fetched"), run=FakeUv())
    assert not (other / runtime.MARKER).exists()


def test_remove_refuses_a_folder_without_the_installers_mark(tmp_path, monkeypatch):
    other = tmp_path / "someone-elses"
    other.mkdir()
    (other / "keep.txt").write_text("冒険", encoding="utf-8")
    monkeypatch.setenv("SURASURA_IRODORI_HOME", str(other))
    with pytest.raises(runtime.InstallError, match="wasn't made by Surasura's installer"):
        runtime.remove()
    assert (other / "keep.txt").exists()


def test_an_older_runtime_reads_stale_not_installed(installed):
    with open(os.path.join(installed, "installed.json"), "w", encoding="utf-8") as f:
        json.dump({"version": runtime.RUNTIME_VERSION - 1, "backend": "cpu"}, f)
    got = runtime.status()
    assert got["stale"] and not got["installed"]


def test_a_test_never_reaches_the_real_runtime_folder(monkeypatch):
    monkeypatch.delenv("SURASURA_TEST_ROOT")
    with pytest.raises(RuntimeError):
        runtime.home()


# --- the server --------------------------------------------------------------------------------------------------- #
def test_the_server_starts_on_loopback_with_its_own_key_offline_and_below_normal(installed):
    seen = {}

    def popen(cmd, **kw):
        seen.update(cmd=cmd, **kw)
        return mock.Mock(poll=mock.Mock(return_value=None), pid=None)
    srv = server.Server(popen=popen, opener=lambda *a, **k: io.BytesIO(b'{"status":"ok"}'))
    srv.start()
    env = seen["env"]
    assert seen["cmd"][1:4] == ["-I", "-X", "utf8"] and seen["cmd"][4].endswith("host.py")
    assert env["HF_HUB_OFFLINE"] == "1" and env["IRODORI_API_KEY"] == srv.key and len(srv.key) == 32
    assert env["IRODORI_MODEL_DEVICE"] == "cpu" and env["IRODORI_PARENT_PID"] == str(os.getpid())
    if sys.platform == "win32":
        assert seen["creationflags"] & server.BELOW_NORMAL
    srv.stop()


def test_a_server_that_dies_as_it_starts_says_so(installed):
    srv = server.Server(popen=lambda *a, **k: mock.Mock(poll=mock.Mock(return_value=1), pid=None),
                        opener=lambda *a, **k: io.BytesIO(b"{}"))
    with pytest.raises(server.ServerError, match="stopped as it started"):
        srv.start()


def test_not_installed_never_starts_a_server():
    with pytest.raises(server.ServerError, match="isn't installed"):
        server.Server(popen=lambda *a, **k: pytest.fail("started")).start()


def test_speak_sends_the_key_the_caption_and_k2s_speed():
    sent = {}

    def opener(req, timeout=None):
        sent.update(url=req.full_url, auth=req.get_header("Authorization"), body=json.loads(req.data))
        return io.BytesIO(WAV)
    srv = server.Server(opener=opener)
    srv.proc, srv.port, srv.key = mock.Mock(poll=mock.Mock(return_value=None)), 51234, "k" * 32
    assert srv.speak("冒険だ。", "20代の女性の自然な声。", speed=1.1, seed=5) == WAV
    assert sent["url"] == "http://127.0.0.1:51234/v1/audio/speech" and sent["auth"] == f"Bearer {'k' * 32}"
    assert sent["body"]["speed"] == 1.1 and sent["body"]["irodori"]["caption"] == "20代の女性の自然な声。"
    assert sent["body"]["voice"] == "none" and sent["body"]["response_format"] == "wav"


def test_something_that_isnt_audio_is_refused():
    srv = server.Server(opener=lambda *a, **k: io.BytesIO(b"<html>"))
    srv.proc, srv.port, srv.key = mock.Mock(poll=mock.Mock(return_value=None)), 1, "k"
    with pytest.raises(server.ServerError, match="isn't audio"):
        srv.speak("冒険だ。", None)


def test_the_host_listens_on_loopback_only_and_ends_with_its_parent():
    src = open(os.path.join(os.path.dirname(runtime.__file__), "host.py"), encoding="utf-8").read()
    assert 'host="127.0.0.1"' in src and "0.0.0.0" not in src and "IRODORI_PARENT_PID" in src


# --- the run --------------------------------------------------------------------------------------------------------- #
class FakeServer:
    def __init__(self, fail=()):
        self.spoken, self.fail, self.started, self.stopped = [], set(fail), 0, 0

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1

    def speak(self, text, caption, **kw):
        if text in self.fail:
            raise server.ServerError("The AI voice didn't answer (timed out).")
        self.spoken.append((text, caption, kw))
        return WAV


@pytest.fixture
def no_ffmpeg(monkeypatch):
    monkeypatch.setattr(make, "_ffmpeg", lambda: None)              # the wav is the clip


def test_a_run_asks_the_voice_only_for_cards_with_no_audio_and_writes_once(anki, installed, shared_writer,
                                                                           no_ffmpeg):
    srv = FakeServer()
    report = make.make_for_notes({}, "ja", list(anki.notes), srv=srv)
    assert report["ok"], report
    assert [t for t, _c, _k in srv.spoken] == ["彼は毎日冒険に出かけます。", "素晴らしい冒険が待っているはずだ。"]
    assert sorted(report["written"]) == [101, 104] and report["run"]
    assert anki.notes[102]["SentenceAudio"] == "[sound:sl-3f9a1c2b7d4e5f60.mp3]"       # a clip: never asked
    assert anki.notes[103]["SentenceAudio"] == "<br>" and anki.notes[105]["SentenceAudio"] == "ナレーター"
    assert anki.notes[106]["SentenceAudio"] == "  \n"                   # spaces hold something: never written
    assert anki.notes[101]["SentenceAudio"].startswith("[sound:surasura-sa-")
    assert all(kw["speed"] == 1.1 for _t, _c, kw in srv.spoken)
    assert anki.tags[101] == {writer.AI_TAG}
    writes = [held for a, _p, held in anki.requests if a in WRITES]
    assert writes and all(writes)                                   # every write under the Anki-write lock


def test_the_count_is_a_dry_run_asking_no_voice_and_writing_nothing(anki, installed, shared_writer):
    srv = FakeServer()
    report = make.make_for_notes({}, "ja", list(anki.notes), dry_run=True, srv=srv)
    assert report["todo"] == 2 and not srv.spoken and not report["written"]
    assert make.count_line(report) == "2 cards have no sentence audio."
    assert not [a for a, _p, _h in anki.requests if a in WRITES]


def test_the_count_names_the_lines_the_voice_cant_read():
    assert make.count_line({"todo": 1, "skipped": {"too long": 2}}) == \
        "1 card has no sentence audio. 2 more can't be read aloud (too long, or no Japanese)."
    assert make.count_line({"todo": 0}) == "Every card here already has sentence audio."


def test_a_second_run_while_one_holds_the_voice_is_refused_as_busy(anki, installed, shared_writer):
    from app import path_utils
    held = runtime.running()
    try:
        srv = FakeServer()
        report = make.make_for_notes({}, "ja", list(anki.notes), srv=srv)
    finally:
        path_utils.release_lock(held)
    assert report["busy"] and report["problems"] == [make.BUSY] and not srv.spoken


def test_another_language_is_refused_before_anki_is_asked(anki, installed, shared_writer):
    report = make.make_for_notes({}, "zh", list(anki.notes), srv=FakeServer())
    assert not report["ok"] and not anki.requests


def test_a_run_that_wrote_keeps_its_undo_for_a_later_window(anki, installed, shared_writer, no_ffmpeg):
    report = make.make_for_notes({}, "ja", list(anki.notes), srv=FakeServer(), source="backfill")
    assert irodori.last_run("ja", "backfill")["run"] == report["run"]
    assert irodori.last_run("ja", "connect") is None
    irodori.undo({}, "ja", report["run"])
    assert irodori.last_run("ja", "backfill") is None


def test_a_clip_that_cant_be_written_is_said_never_raised(anki, installed, shared_writer, monkeypatch):
    def broken(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(make, "make_clips", broken)
    report = make.make_for_notes({}, "ja", list(anki.notes), srv=FakeServer())
    assert not report["ok"] and "disk full" in report["problems"][-1]


def test_not_installed_writes_nothing_and_says_where_to_install(anki, shared_writer):
    report = make.make_for_notes({}, "ja", list(anki.notes), srv=FakeServer())
    assert not report["ok"] and "Settings › App › Beta" in report["problems"][0]


def test_without_the_shared_writer_no_voice_is_asked(anki, installed, monkeypatch):
    monkeypatch.setattr(writer, "_shared", lambda: None)
    srv = FakeServer()
    report = make.make_for_notes({}, "ja", list(anki.notes), srv=srv)
    assert not report["ok"] and report["problems"] == [writer.WAITS] and not srv.spoken


def test_stop_part_way_writes_what_was_made_and_the_next_run_reuses_the_clip(anki, installed, shared_writer,
                                                                             no_ffmpeg):
    cancel, srv = threading.Event(), FakeServer()

    def say(done, of, _text):
        if done == 1:
            cancel.set()
    first = make.make_for_notes({}, "ja", list(anki.notes), srv=srv, cancel=cancel, say=say)
    assert first["stopped"] and first["written"] == [101]
    anki.notes[101]["SentenceAudio"] = ""                          # (the learner took it off again)
    again = FakeServer()
    second = make.make_for_notes({}, "ja", list(anki.notes), srv=again)
    assert sorted(second["written"]) == [101, 104]
    assert [t for t, _c, _k in again.spoken] == ["素晴らしい冒険が待っているはずだ。"]   # 101's clip kept


def test_a_sentence_the_voice_fails_is_named_and_the_others_are_written(anki, installed, shared_writer, no_ffmpeg):
    report = make.make_for_notes({}, "ja", list(anki.notes), srv=FakeServer(fail={"彼は毎日冒険に出かけます。"}))
    assert report["written"] == [104] and not report["ok"]
    assert "didn't answer" in report["problems"][0]


def test_three_failures_in_a_row_end_the_run(installed):
    todo = [(n, f"冒険{n}だ。") for n in range(6)]
    srv = FakeServer(fail={t for _n, t in todo})
    files, failed = make.make_clips(todo, voice.pack(), srv=srv, ffmpeg=None)
    assert not files and sum(failed.values()) == 3


def test_on_a_gpu_the_voice_pauses_after_each_burst(installed):
    with open(os.path.join(installed, "installed.json"), "w", encoding="utf-8") as f:
        json.dump({"version": runtime.RUNTIME_VERSION, "backend": "cu126"}, f)
    slept = []
    todo = [(n, f"冒険{n}だ。") for n in range(make.BURST + 2)]
    make.make_clips(todo, voice.pack(), srv=FakeServer(), sleep=slept.append, ffmpeg=None)
    assert len(slept) == make.PAUSE_S                               # one pause, after the first 15


def test_on_the_cpu_there_is_no_pause(installed):
    slept = []
    make.make_clips([(n, f"冒険{n}だ。") for n in range(make.BURST + 2)], voice.pack(), srv=FakeServer(),
                    sleep=slept.append, ffmpeg=None)
    assert not slept


def test_an_mp3_is_made_when_ffmpeg_can_else_the_wav_stays(installed, monkeypatch):
    def fake_ffmpeg(cmd, **kw):
        open(cmd[-1], "wb").write(b"ID3mp3")
        return mock.Mock(returncode=0)
    monkeypatch.setattr(make.subprocess, "run", fake_ffmpeg)
    files, _ = make.make_clips([(1, "冒険だ。")], voice.pack(), srv=FakeServer(), ffmpeg="ffmpeg.exe")
    assert files[1].endswith(".mp3") and open(files[1], "rb").read() == b"ID3mp3"
    monkeypatch.setattr(make.subprocess, "run", lambda cmd, **kw: mock.Mock(returncode=1))
    files, _ = make.make_clips([(2, "冒険する？")], voice.pack(), srv=FakeServer(), ffmpeg="ffmpeg.exe")
    assert files[2].endswith(".wav")


def test_the_undo_of_a_run_goes_through_the_shared_writer(anki, installed, shared_writer, no_ffmpeg):
    report = make.make_for_notes({}, "ja", list(anki.notes), srv=FakeServer())
    undone = irodori.undo({}, "ja", report["run"])
    assert undone["ok"] and anki.notes[101]["SentenceAudio"] == "" and anki.notes[104]["SentenceAudio"] == ""
    assert anki.notes[102]["SentenceAudio"] == "[sound:sl-3f9a1c2b7d4e5f60.mp3]"


def test_find_empty_asks_anki_for_an_empty_field_in_the_deck(anki):
    make.find_empty(URL, "日本語::本「杜子春」")
    assert anki.query == '"deck:日本語::本「杜子春」" "SentenceAudio:" "Sentence:_*"'


# --- Connect's queue ------------------------------------------------------------------------------------------------- #
def test_the_queue_lives_outside_the_runtime_so_remove_never_takes_it(installed, shared_writer):
    queue.add("ja", [101])
    runtime.remove()
    assert queue.waiting("ja") == 1


def test_the_queue_keeps_a_part_once_and_runs_only_while_the_beta_is_on(installed, shared_writer):
    assert queue.add("ja", [101, 104], {"job": 7}) == 2
    assert queue.add("ja", [104]) == 0
    calls = []
    got = queue.run({"enable_irodori": False}, "ja", make_for_notes=lambda *a, **k: calls.append(a))
    assert not calls and got["left"] == 2


def test_a_queued_part_goes_once_written_and_a_stopped_one_waits(installed, shared_writer):
    queue.add("ja", [101, 104])
    queue.add("ja", [105])
    reports = iter([{"ok": True, "written": [101, 104], "run": "ai-1", "todo": 2},
                    {"ok": True, "written": [], "stopped": True, "todo": 1}])
    got = queue.run({"enable_irodori": True}, "ja", make_for_notes=lambda *a, **k: next(reports))
    assert got["written"] == 2 and got["runs"] == ["ai-1"] and got["left"] == 1


def test_a_part_that_keeps_failing_is_dropped_after_its_tries(installed, shared_writer):
    queue.add("ja", [101])
    calls = []

    def fails(*a, **k):
        calls.append(a)
        return {"ok": False, "todo": 1, "problems": ["The AI voice didn't start."]}
    got = queue.run({"enable_irodori": True}, "ja", make_for_notes=fails)
    assert got["left"] == 0 and len(calls) == queue.TRIES


def test_should_stop_ends_the_queue_before_any_run(installed, shared_writer):
    queue.add("ja", [101])
    got = queue.run({"enable_irodori": True}, "ja", should_stop=lambda: True,
                    make_for_notes=lambda *a, **k: pytest.fail("ran"))
    assert got["left"] == 1
