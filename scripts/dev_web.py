from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
API_URL = "http://127.0.0.1:8731/api/health"
WEB_URL = "http://127.0.0.1:3000"


@dataclass
class ManagedProcess:
    name: str
    process: subprocess.Popen[bytes] | None
    reused: bool = False


def main() -> int:
    processes: list[ManagedProcess] = []

    if _url_responds(API_URL):
        print(f"[api] already running at {API_URL}")
        processes.append(ManagedProcess("api", None, reused=True))
    else:
        processes.append(_start_process(
            "api",
            [
                str(ROOT / ".venv" / "Scripts" / "python.exe"),
                "-m",
                "uvicorn",
                "app.web_api:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8731",
                "--reload",
            ],
        ))

    if _url_responds(WEB_URL):
        print(f"[web] already running at {WEB_URL}")
        processes.append(ManagedProcess("web", None, reused=True))
    else:
        processes.append(_start_process(
            "web",
            ["cmd", "/c", "npx", "next", "dev", "web", "-H", "127.0.0.1", "-p", "3000"],
        ))

    print(f"VCG AutoCaption web app: {WEB_URL}")
    try:
        while True:
            for managed in processes:
                if managed.process is None:
                    continue
                name = managed.name
                process = managed.process
                code = process.poll()
                if code is not None:
                    _terminate_all(processes)
                    print(f"[{name}] exited with {code}")
                    return code
            time.sleep(0.5)
    except KeyboardInterrupt:
        _terminate_all(processes)
        return 130


def _start_process(name: str, command: list[str]) -> ManagedProcess:
    # Inherit the VS Code terminal streams. Uvicorn's Windows reload supervisor
    # starts its own child process and is not reliable behind a daemon-threaded
    # output pipe; inheriting the console also ensures startup errors are never
    # lost when a child exits quickly.
    process = subprocess.Popen(command, cwd=ROOT)
    return ManagedProcess(name, process)


def _terminate_all(processes: list[ManagedProcess]) -> None:
    for managed in processes:
        process = managed.process
        if process is None:
            continue
        if process.poll() is None:
            process.terminate()
    for managed in processes:
        process = managed.process
        if process is None:
            continue
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def _url_responds(url: str) -> bool:
    try:
        with urlopen(url, timeout=2) as response:
            return 200 <= response.status < 500
    except URLError:
        return False
    except OSError:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
