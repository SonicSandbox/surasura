# SPDX-License-Identifier: GPL-3.0-or-later
"""Runs the Irodori server inside the voice's own Python (the runtime's `env`), never in Surasura's (README § Running).

Started by `server.Server.start` as `<runtime>/env/python.exe -I host.py <port>`, with the server's settings in its
environment (IRODORI_*: the model files, the per-start key, the device; HF_HUB_OFFLINE=1). Listens on 127.0.0.1 only.
It ends by itself when the process that started it ends (checked every 2 s) or after IRODORI_IDLE_S seconds with no
request, so no model is ever left holding memory. Standard library + the runtime's own packages only.
"""
import os
import sys
import threading
import time


def _alive(pid):
    if sys.platform == "win32":
        import ctypes
        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x00100000 | 0x1000, False, pid)        # SYNCHRONIZE | QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            return kernel.WaitForSingleObject(handle, 0) == 0x102                # WAIT_TIMEOUT: still running
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def main():
    port = int(sys.argv[1])
    parent = int(os.environ.get("IRODORI_PARENT_PID") or 0)
    idle = float(os.environ.get("IRODORI_IDLE_S") or 300)
    last = [time.monotonic()]
    busy = [0]

    def watch():
        while True:
            time.sleep(2)
            if parent and not _alive(parent):
                os._exit(0)
            if not busy[0] and time.monotonic() - last[0] > idle:
                os._exit(0)
    threading.Thread(target=watch, daemon=True).start()

    import uvicorn
    from irodori_openai_tts.app import app

    @app.middleware("http")
    async def _touch(request, call_next):
        busy[0] += 1
        last[0] = time.monotonic()
        try:
            return await call_next(request)
        finally:
            busy[0] -= 1
            last[0] = time.monotonic()

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
