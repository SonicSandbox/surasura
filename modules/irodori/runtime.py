# SPDX-License-Identifier: GPL-3.0-or-later
"""The voice's own environment: what *Install* downloads, where it lives, and *Remove* (README § Install and remove).

Nothing here is in Surasura's requirements: on the learner's press the runtime is built under `home()` —
`%LOCALAPPDATA%\\Houseki\\Surasura\\irodori\\` (one per user, every install shares it; never roaming) — by `uv`:
its own Python 3.10, PyTorch (CPU, or CUDA for a GPU that can hold the model), the Irodori server's pinned packages
(`requirements-server.txt`, exported from the server's `uv.lock` at its pinned commit), then the model files from
Hugging Face. Every download is pinned. Checked by hash: uv, the model files, the watermark (sha256 / git blob hash,
here), the server's PyPI packages and the CPU PyTorch (`--require-hashes`, from the server's own lock). By pinned
commit only: the server and its three git dependencies (GitHub archives). Not pinned: the build tools (setuptools …)
uv fetches from PyPI to build those four.
By pinned version only: a CUDA PyTorch (not in the server's lock). `installed.json` is written last: a cancelled or
failed install is never mistaken for one that works, and the next *Install* picks up where it stopped.

The only network of the module is here, on the learner's press.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile

RUNTIME_VERSION = 1                     # bump when the pins change: an older runtime is offered *Install* again
PYTHON = "3.10.22"
UV = {"version": "0.13.4",
      "url": "https://github.com/astral-sh/uv/releases/download/0.13.4/uv-x86_64-pc-windows-msvc.zip",
      "sha256": "ccec7508a07d9933d7cb1261880633efcf1f30d6e6eddab21823f1dae6f23225"}
TORCH = {"cpu": ("2.10.0+cpu", "https://download.pytorch.org/whl/cpu"),
         "cu126": ("2.10.0+cu126", "https://download.pytorch.org/whl/cu126"),
         "cu128": ("2.10.0+cu128", "https://download.pytorch.org/whl/cu128")}
# The server and its three git dependencies, as GitHub archives at the commits its uv.lock pins (no git needed): by
# commit, not by hash (GitHub doesn't promise an archive's bytes); everything else is installed by hash
ARCHIVES = (
    "irodori-tts-server @ https://github.com/Aratako/Irodori-TTS-Server/archive/61012c760f22f7b4a6c21c5c5f8f9e148120b6f9.zip",
    "irodori-tts @ https://github.com/Aratako/Irodori-TTS/archive/89f9d8fbd4d51ea019867ee1197725ede1df13c5.zip",
    "dacvae @ https://github.com/facebookresearch/dacvae/archive/414c20785fc3a28373073ea8ef7a1316eeeaca6e.zip",
    "silentcipher @ https://github.com/SesameAILabs/silentcipher/archive/d46d7d0893a583d8968ab3a6626e2289faec9152.zip",
)
HF = "https://huggingface.co/{repo}/resolve/{rev}/{path}"
# (repo, revision, path, size, hash) — "sha256:" for an LFS file, "git:" (the git blob sha1) for a small one
MODEL_FILES = (
    ("Aratako/Irodori-TTS-v4.1-Small", "2b28324dc263ed5e6638b3cf3dd94c82ead07b4b", "model.safetensors", 3064295596,
     "sha256:c85de88c01700cb53538e706f128ebcb1b8513ad21d7d0e75f58bc82cdbf89f6"),
    ("Aratako/Irodori-TTS-v4.1-Small", "2b28324dc263ed5e6638b3cf3dd94c82ead07b4b", "tokenizer/tokenizer.json", 6718495,
     "git:1b9a8b7e5e8d37174e6b9e9655cdbd0c9b456af7"),
    ("Aratako/Irodori-TTS-v4.1-Small", "2b28324dc263ed5e6638b3cf3dd94c82ead07b4b", "tokenizer/tokenizer_config.json",
     668, "git:e59d0be2a7fd2bc7f7b85136e46c65a41c1c3634"),
    ("Aratako/Semantic-DACVAE-Japanese-32dim", "47376ee24834d7a05a48ebabfe3cde29b3c5e214", "weights.pth", 429620065,
     "sha256:db120339c5ee7eca1912cdf29bc612b947a0808e69c3cebfb4936b45a762c1d5"),
)
# The model card's watermark (SilentCipher, Sony; code MIT): Irodori looks it up in the Hugging Face cache, so it is
# laid out there (`hf/hub/models--sony--silentcipher`), its ref pinned, and the server runs with HF_HUB_OFFLINE=1
WATERMARK_REPO, WATERMARK_REV = "Sony/SilentCipher", "a1c4d021905e0dc5b24be5f68db5fc4dba410ee1"
WATERMARK_FILES = (
    ("config.json", 51, "git:55945ba983190a14e19267f19b745da44d14b87f"),
    ("44_1_khz/73999_iteration/hparams.yaml", 1474, "git:41c69dfaabdf288dd8ecc8f0aa59f73d211537e8"),
    ("44_1_khz/73999_iteration/enc_c.ckpt", 184765,
     "sha256:ff64f80d2391fdfc888e4103c499be4a2c958e59626587a1eab6db93204814c7"),
    ("44_1_khz/73999_iteration/dec_c.ckpt", 2008794,
     "sha256:c23b57635172b2fbd3a8531d15ba76b5885a10d0fe902ccb823c521c56041b33"),
    ("44_1_khz/73999_iteration/dec_m_0.ckpt", 9554818,
     "sha256:829540c058270d29788f05294894d45bf436e44add0e1099422242ebb94b7088"),
)
# What the learner is told before the press (measured 2026-11-11 on Windows: the CPU runtime 4.9 GB in all; the CUDA
# environment 4.7 GB against the CPU's 1.3)
SIZE_GB = {"cpu": 5.0, "cu126": 8.5, "cu128": 8.5}
GPU_MIN_MB = 6000                       # PROVISIONAL: a 3 GB card spills the model into system memory — slower than the CPU
DRIVER_MIN = 525                        # CUDA 12.x
MARKER = ".surasura-irodori"            # written first: *Remove* deletes only a folder that carries it
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
BELOW_NORMAL = 0x00004000 if sys.platform == "win32" else 0


class Cancelled(Exception):
    pass


class InstallError(Exception):
    pass


# --- where ----------------------------------------------------------------------------------------------------------- #
def home():
    """The runtime's folder (made by `install`, never here): `irodori/` in the per-user local root (path_utils.PARTS:
    it stays through a Start over, like the tools). SURASURA_IRODORI_HOME moves it (tests/live_drill.py, the
    by-hand check on a real runtime)."""
    moved = os.environ.get("SURASURA_IRODORI_HOME")
    if moved:
        return os.path.abspath(moved)
    from app import path_utils
    return os.path.join(path_utils.local_data_root(), "irodori")       # a test root: <root>/local_root/irodori


def env_python(base=None):
    base = base or home()
    return os.path.join(base, "env", "Scripts", "python.exe") if sys.platform == "win32" else \
        os.path.join(base, "env", "bin", "python")


def model_path(base=None):
    return os.path.join(base or home(), "models", "v4.1-small", "model.safetensors")


def codec_path(base=None):
    return os.path.join(base or home(), "models", "codec", "weights.pth")


def hf_home(base=None):
    return os.path.join(base or home(), "hf")


def _installed_file(base=None):
    return os.path.join(base or home(), "installed.json")


def status():
    """-> {"installed": bool, "stale" (an older runtime), "backend", "size_bytes", "version", "home"}. A file look."""
    base = home()
    try:
        with open(_installed_file(base), "r", encoding="utf-8") as f:
            got = json.load(f)
    except (OSError, ValueError):
        got = None
    ok = isinstance(got, dict) and os.path.isfile(env_python(base)) and os.path.isfile(model_path(base)) and \
        os.path.isfile(codec_path(base))
    current = ok and got.get("version") == RUNTIME_VERSION
    return {"installed": bool(current), "stale": bool(ok and not current), "home": base,
            "backend": (got or {}).get("backend") if ok else None,
            "size_bytes": (got or {}).get("size_bytes") if ok else None, "version": (got or {}).get("version")}


def ready():
    return status()["installed"]


# --- which backend --------------------------------------------------------------------------------------------------- #
def gpu(run=subprocess.run):
    """This PC's NVIDIA GPU as nvidia-smi says -> {"name", "memory_mb", "driver", "compute"} or None (none, no driver,
    nvidia-smi missing). The largest card if there are several."""
    try:
        out = run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version,compute_cap",
                   "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=15,
                  creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None
    if getattr(out, "returncode", 1) != 0:
        return None
    best = None
    for line in (out.stdout or "").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        try:
            card = {"name": parts[0], "memory_mb": int(float(parts[1])), "driver": parts[2],
                    "compute": float(parts[3])}
        except ValueError:
            continue
        if best is None or card["memory_mb"] > best["memory_mb"]:
            best = card
    return best


def backend(card="look"):
    """"cu128" (compute capability 12+), "cu126" (an NVIDIA GPU with GPU_MIN_MB and a driver ≥ 525), else "cpu"."""
    card = gpu() if card == "look" else card
    if not card or card["memory_mb"] < GPU_MIN_MB:
        return "cpu"
    try:
        driver = int(str(card["driver"]).split(".")[0])
    except ValueError:
        return "cpu"
    if driver < DRIVER_MIN:
        return "cpu"
    return "cu128" if card["compute"] >= 12.0 else "cu126"


# --- install --------------------------------------------------------------------------------------------------------- #
STEPS = ("the installer", "Python", "PyTorch", "the voice's programs", "the voice model", "the watermark")


def install(say=None, cancel=None, chosen=None, opener=urllib.request.urlopen, run=subprocess.Popen):
    """Build the runtime (README § Install) -> its status. `say(step, of, text)` reports each step; `cancel` (an Event)
    stops it between two steps and inside a download or a uv run (Cancelled). A step done before is skipped or quick.
    Raises InstallError with a plain reason. `opener` / `run`: the network and the process, replaceable by a test."""
    say = say or (lambda step, of, text: None)
    base = home()
    if os.path.isdir(base) and set(os.listdir(base)) - {RUN_LOCK} and not os.path.isfile(os.path.join(base, MARKER)):
        raise InstallError(f"{base} already holds other files, so nothing was installed there.")
    os.makedirs(base, exist_ok=True)
    _mark(base)
    chosen = chosen or backend()
    try:
        os.remove(_installed_file(base))           # a new install: never "installed" until its last step
    except OSError:
        pass
    of = len(STEPS)
    env = _uv_env(base)
    say(1, of, STEPS[0])
    uv = _get_uv(base, opener, cancel)
    _check(cancel)
    say(2, of, STEPS[1])
    if not os.path.isfile(env_python(base)):
        _run([uv, "venv", "--python", PYTHON, "--managed-python", "--quiet", os.path.join(base, "env")], env, run,
             cancel)
    _check(cancel)
    say(3, of, STEPS[2])
    here = os.path.dirname(os.path.abspath(__file__))
    pip = [uv, "pip", "install", "--quiet", "--python", env_python(base), "--no-deps"]
    version, index = TORCH[chosen]
    if chosen == "cpu":                         # the lock's own CPU wheels, by hash
        _run(pip + ["--require-hashes", "-r", os.path.join(here, "requirements-torch-cpu.txt"), "--index-url", index],
             env, run, cancel)
    else:                                       # a CUDA build isn't in the server's lock: by its pinned version
        _run(pip + [f"torch=={version}", f"torchaudio=={version}", "--index-url", index], env, run, cancel)
    _check(cancel)
    say(4, of, STEPS[3])
    _run(pip + ["--require-hashes", "-r", os.path.join(here, "requirements-server.txt")], env, run, cancel)
    _run(pip + list(ARCHIVES), env, run, cancel)
    _check(cancel)
    say(5, of, STEPS[4])
    for repo, rev, path, size, digest in MODEL_FILES:
        folder = os.path.dirname(model_path(base)) if "Irodori" in repo else os.path.dirname(codec_path(base))
        _fetch(HF.format(repo=repo, rev=rev, path=path), os.path.join(folder, *path.split("/")), size, digest, opener,
               cancel)
    say(6, of, STEPS[5])
    snap = os.path.join(hf_home(base), "hub", "models--sony--silentcipher")
    for path, size, digest in WATERMARK_FILES:
        _fetch(HF.format(repo=WATERMARK_REPO, rev=WATERMARK_REV, path=path),
               os.path.join(snap, "snapshots", WATERMARK_REV, *path.split("/")), size, digest, opener, cancel)
    os.makedirs(os.path.join(snap, "refs"), exist_ok=True)
    with open(os.path.join(snap, "refs", "main"), "w", encoding="ascii") as f:
        f.write(WATERMARK_REV)
    shutil.rmtree(os.path.join(base, "cache"), ignore_errors=True)      # uv's downloads: not needed any more
    record = {"version": RUNTIME_VERSION, "backend": chosen, "python": PYTHON, "torch": version,
              "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "size_bytes": _size(base)}
    tmp = _installed_file(base) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=1)
    os.replace(tmp, _installed_file(base))
    return status()


def remove(stop=None):
    """Delete the runtime (*Remove*): the server stopped first (`stop`), then the folder — only one carrying MARKER,
    the folder install made (never a folder the setting or a test pointed elsewhere). -> the bytes freed. The cards'
    audio already in Anki stays. Raises InstallError when a file can't go (a server still holding it)."""
    base = home()
    if not os.path.isdir(base):
        return 0
    marker = os.path.join(base, MARKER)
    if not os.path.isfile(marker):
        if set(os.listdir(base)) <= {RUN_LOCK}:     # only a stray lock left behind: tidy it
            _drop(os.path.join(base, RUN_LOCK))
            try:
                os.rmdir(base)
            except OSError:
                pass
            return 0
        raise InstallError(f"{base} wasn't made by Surasura's installer, so it was left alone.")
    held = running()
    if held is None:
        raise InstallError("The AI voice is making audio now. Press Remove once it has finished.")
    try:
        if stop is not None:
            stop()
        freed = _size(base)
        errors = []
        for name in os.listdir(base):           # everything but the mark first: a Remove that fails can run again
            path = os.path.join(base, name)
            if name in (MARKER, RUN_LOCK):
                continue
            if os.path.isdir(path):
                shutil.rmtree(path, onerror=lambda fn, p, info: errors.append(p))
            else:
                try:
                    os.remove(path)
                except OSError:
                    errors.append(path)
        if errors:
            raise InstallError("Some files are still in use. Close Surasura's other windows and press Remove again.")
    finally:
        from app import path_utils
        path_utils.release_lock(held)
    for name in (RUN_LOCK, MARKER):
        _drop(os.path.join(base, name))
    try:
        os.rmdir(base)
    except OSError:
        pass
    return freed


RUN_LOCK = "run.lock"


def running():
    """The runtime's one-run lock (`<runtime>/run.lock`, an OS lock: across every Surasura process) -> the held lock,
    or None when a run (or a Remove) holds it. Release with `path_utils.release_lock`."""
    from app import path_utils
    base = home()
    if not os.path.isfile(os.path.join(base, MARKER)):
        return None                             # nothing installed: no run, and no folder made for its lock
    return path_utils.try_lock(os.path.join(base, RUN_LOCK))


# --- small parts ----------------------------------------------------------------------------------------------------- #
def _mark(base):
    path = os.path.join(base, MARKER)
    if not os.path.isfile(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write("Surasura's AI audio runtime (modules/irodori). Settings › App › Beta › Remove deletes this folder.\n")


def _uv_env(base):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "UV_", "VIRTUAL_ENV", "CONDA"))}
    env.update(UV_CACHE_DIR=os.path.join(base, "cache"), UV_PYTHON_INSTALL_DIR=os.path.join(base, "python"),
               UV_NO_CONFIG="1", UV_NO_PROGRESS="1")
    return env


def _check(cancel):
    if cancel is not None and cancel.is_set():
        raise Cancelled()


def _get_uv(base, opener, cancel):
    folder = os.path.join(base, "uv", UV["version"])
    exe = os.path.join(folder, "uv.exe" if sys.platform == "win32" else "uv")
    if os.path.isfile(exe):
        return exe
    archive = os.path.join(base, "uv", f"uv-{UV['version']}.zip")
    _fetch(UV["url"], archive, None, f"sha256:{UV['sha256']}", opener, cancel)
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            if os.path.basename(name) in ("uv.exe", "uvx.exe", "uv", "uvx") and not name.endswith("/"):
                target = os.path.join(folder, os.path.basename(name))
                os.makedirs(folder, exist_ok=True)
                with z.open(name) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
    os.remove(archive)
    if not os.path.isfile(exe):
        raise InstallError("The installer's download had no uv in it.")
    return exe


def _run(cmd, env, run, cancel):
    """One uv command, no window, below-normal priority; Cancel ends it. Fails with uv's last line."""
    try:
        proc = run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                   creationflags=NO_WINDOW | BELOW_NORMAL)
    except OSError as e:
        raise InstallError(f"Couldn't start the installer ({e}).") from None
    lines = []
    while True:
        if cancel is not None and cancel.is_set():
            proc.kill()
            proc.wait()
            raise Cancelled()
        try:
            out, _ = proc.communicate(timeout=1)
            if out:
                lines += out.decode("utf-8", "replace").splitlines()
            break
        except subprocess.TimeoutExpired:
            continue
    if proc.returncode != 0:
        last = next((ln for ln in reversed(lines) if ln.strip()), f"exit code {proc.returncode}")
        raise InstallError(_plain(last))


def _plain(line):
    """uv's error line, shortened for the window: a network failure said as one."""
    if re.search(r"(?i)dns|connect|timed out|network|resolve host|tls", line):
        return "The download failed: check the internet connection, then press Install again."
    return line.strip()[:300]


def _fetch(url, target, size, digest, opener, cancel):
    """Download `url` to `target` (a `.part` beside it, renamed only once its hash is right). A file already there with
    the right size and hash is kept (a resumed install)."""
    if os.path.isfile(target) and (size is None or os.path.getsize(target) == size) and _matches(target, digest):
        return
    os.makedirs(os.path.dirname(target), exist_ok=True)
    part = f"{target}.part"
    try:
        with opener(urllib.request.Request(url, headers={"User-Agent": "Surasura"}), timeout=60) as r, \
                open(part, "wb") as f:
            while True:
                _check(cancel)
                block = r.read(1 << 20)
                if not block:
                    break
                f.write(block)
    except Cancelled:
        _drop(part)
        raise
    except OSError as e:
        _drop(part)
        raise InstallError("The download failed: check the internet connection, then press Install again.") from e
    if (size is not None and os.path.getsize(part) != size) or not _matches(part, digest):
        _drop(part)
        raise InstallError(f"A download didn't match what was expected ({os.path.basename(target)}), so it was "
                           "thrown away. Press Install again.")
    os.replace(part, target)


def _matches(path, digest):
    kind, _, want = digest.partition(":")
    if kind == "sha256":
        h = hashlib.sha256()
    elif kind == "git":
        h = hashlib.sha1(f"blob {os.path.getsize(path)}\0".encode())
    else:
        return False
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest() == want


def _drop(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _size(base):
    total = 0
    for root, _dirs, files in os.walk(base):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total
