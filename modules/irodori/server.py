# SPDX-License-Identifier: GPL-3.0-or-later
"""The voice's server: started when there is work, stopped when it is done (README § Running).

`Server` runs `host.py` in the runtime's own Python on a free 127.0.0.1 port with a key made for this start (the
server refuses any request without it), below-normal priority, no window. `speak` sends one sentence and returns the
wav bytes. Nothing here talks to anything but 127.0.0.1.
"""
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

from modules.irodori import runtime

START_S = 240                           # the host listening: a cold first start imports torch (and a scan of new DLLs)
SPEAK_S = 900                           # one sentence, the model's load included, on a slow or busy CPU
IDLE_S = 300                            # PROVISIONAL: host.py ends itself after 5 idle minutes
BELOW_NORMAL = 0x00004000
_LOOPBACK = "127.0.0.1"


class ServerError(Exception):
    pass


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((_LOOPBACK, 0))
        return s.getsockname()[1]


def _device(backend):
    return "cpu" if backend in (None, "cpu") else "cuda"


class Server:
    """One running server. `start()`, `speak(text, caption, ...)`, `stop()`; a context manager stops it."""

    def __init__(self, base=None, popen=subprocess.Popen, opener=None):
        self.base = base or runtime.home()
        # loopback, never a system proxy: the key and the sentences go nowhere but 127.0.0.1
        self.popen = popen
        self.opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({})).open
        self.proc = self.port = self.key = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()

    def environment(self, backend):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "IRODORI_", "HF_", "VIRTUAL_ENV"))}
        env.update({
            "IRODORI_CHECKPOINT": runtime.model_path(self.base), "IRODORI_CODEC_REPO": runtime.codec_path(self.base),
            "IRODORI_MODEL_DEVICE": _device(backend), "IRODORI_CODEC_DEVICE": _device(backend),
            "IRODORI_API_KEY": self.key, "IRODORI_VOICES_DIR": os.path.join(self.base, "run", "voices"),
            "IRODORI_ALLOW_NO_REF_VOICE": "true", "IRODORI_MAX_CONCURRENT_SYNTHESIS": "1",
            "IRODORI_PARENT_PID": str(os.getpid()), "IRODORI_IDLE_S": str(IDLE_S),
            "HF_HOME": runtime.hf_home(self.base), "HF_HUB_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1",
            "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1", "GRADIO_ANALYTICS_ENABLED": "False",
            "WANDB_MODE": "disabled", "DO_NOT_TRACK": "1",
        })
        return env

    def start(self):
        if self.proc is not None and self.proc.poll() is None:
            return self
        state = runtime.status()
        if not state["installed"]:
            raise ServerError("The AI voice isn't installed.")
        self.key, self.port = secrets.token_hex(16), _free_port()
        run_dir = os.path.join(self.base, "run")
        os.makedirs(os.path.join(run_dir, "voices"), exist_ok=True)
        host = os.path.join(os.path.dirname(os.path.abspath(__file__)), "host.py")
        log = open(os.path.join(run_dir, "server.log"), "wb")             # this start's only: never grows
        flags = (0x08000000 | BELOW_NORMAL) if sys.platform == "win32" else 0         # no window, below normal
        try:
            self.proc = self.popen([runtime.env_python(self.base), "-I", "-X", "utf8", host, str(self.port)],
                                   env=self.environment(state["backend"]), cwd=run_dir, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
        except OSError as e:
            raise ServerError(f"The AI voice couldn't start ({e}).") from None
        finally:
            log.close()
        deadline = time.monotonic() + START_S
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise ServerError("The AI voice stopped as it started (its log: run/server.log).")
            if self._health():
                return self
            time.sleep(0.5)
        self.stop()
        raise ServerError("The AI voice didn't start in time.")

    def _health(self):
        try:
            with self.opener(f"http://{_LOOPBACK}:{self.port}/health", timeout=2) as r:
                return json.loads(r.read().decode("utf-8")).get("status") == "ok"
        except (OSError, ValueError):
            return False

    def speak(self, text, caption, speed=1.1, seed=7, num_steps=None, lora=None, voice="none"):
        """One sentence -> the wav bytes. Raises ServerError (the server gone, a refusal)."""
        if self.proc is None or self.proc.poll() is not None:
            raise ServerError("The AI voice isn't running.")
        options = {"seed": int(seed)}
        if caption:
            options["caption"] = caption
        if num_steps:
            options["num_steps"] = int(num_steps)
        if lora:
            options["lora_adapter"] = lora
        body = json.dumps({"model": "irodori-tts", "input": text, "voice": voice, "response_format": "wav",
                           "speed": float(speed), "irodori": options}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(f"http://{_LOOPBACK}:{self.port}/v1/audio/speech", body,
                                     {"Content-Type": "application/json", "Authorization": f"Bearer {self.key}"})
        try:
            with self.opener(req, timeout=SPEAK_S) as r:
                data = r.read()
        except urllib.error.HTTPError as e:
            raise ServerError(f"The AI voice refused the sentence ({e.code}).") from None
        except OSError as e:
            raise ServerError(f"The AI voice didn't answer ({e}).") from None
        if not data.startswith(b"RIFF"):
            raise ServerError("The AI voice sent something that isn't audio.")
        return data

    def stop(self):
        proc, self.proc = self.proc, None
        if proc is None:
            return
        if proc.poll() is None:
            if sys.platform == "win32" and isinstance(getattr(proc, "pid", None), int):
                # the venv's python.exe is a launcher: the server is its child — the tree ends, never the launcher alone
                try:
                    subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=15,
                                   creationflags=0x08000000)
                except (OSError, subprocess.SubprocessError):
                    pass
            if proc.poll() is None:
                proc.terminate()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(5)
