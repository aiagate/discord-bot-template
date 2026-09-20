"""Linux supervisor: reap detached Codex/AGY children before releasing a run."""

import ctypes
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import FrameType

from app.infrastructure.collective.workspace import atomic_write


def process_start(pid: int) -> str | None:
    """Read the kernel start identity so a recycled PID is never terminated."""
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except (FileNotFoundError, ProcessLookupError):
        return None


def children(pid: int) -> set[int]:
    """Find descendants, including adopted children after double-forking."""
    parents: dict[int, int] = {}
    for path in Path("/proc").glob("[0-9]*/stat"):
        try:
            fields = path.read_text().rsplit(")", 1)[1].split()
            parents[int(path.parent.name)] = int(fields[1])
        except (FileNotFoundError, ProcessLookupError):
            continue
    descendants = {pid}
    previous = 0
    while len(descendants) != previous:
        previous = len(descendants)
        descendants.update(
            child for child, parent in parents.items() if parent in descendants
        )
    return descendants - {pid}


def main() -> None:
    """Supervise the App Server and mark completion only after all children exit."""
    path = Path(sys.argv[1])
    parent = os.getppid()
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
        raise OSError(ctypes.get_errno(), "Cannot become a child subreaper")
    stopping = False

    def stop(_signum: int, _frame: FrameType | None) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    if libc.prctl(1, signal.SIGTERM, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
        raise OSError(ctypes.get_errno(), "Cannot monitor the runner lifetime")
    os.setsid()
    identity = {
        "pid": os.getpid(),
        "start": process_start(os.getpid()),
        "finished": False,
    }
    atomic_write(path, json.dumps(identity))
    if os.getppid() != parent or stopping:
        identity["finished"] = True
        atomic_write(path, json.dumps(identity))
        return
    environment = {
        key: value
        for key, value in os.environ.items()
        if key
        in {
            "PATH",
            "HOME",
            "LANG",
            "CODEX_HOME",
            "OPENAI_API_KEY",
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "GOOGLE_APPLICATION_CREDENTIALS",
            "AGY_HOME",
            "ANTIGRAVITY_HOME",
            "GHQ_ROOT",
            "GIT_TERMINAL_PROMPT",
        }
    }
    process = subprocess.Popen(sys.argv[2:], env=environment)
    try:
        while process.poll() is None and not stopping:
            time.sleep(0.05)
    finally:
        while children(os.getpid()):
            for child in children(os.getpid()):
                try:
                    os.kill(child, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            try:
                while os.waitpid(-1, os.WNOHANG)[0]:
                    pass
            except ChildProcessError:
                pass
            time.sleep(0.05)
        identity["finished"] = True
        atomic_write(path, json.dumps(identity))


if __name__ == "__main__":
    main()
