"""Cross-process lock so only one MCP server instance drives MathMagic/InDesign at a time.

Several Claude sessions can each start their own mathmagic-mcp-pro process; without a lock
two of them could post into MathMagic simultaneously. The lock is an OS byte-range lock on a
file (released automatically if the process dies), holding the owner's pid/op for diagnostics.
"""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

LOCK_PATH = Path(os.environ.get("MATHMAGIC_LOCK_FILE",
                                str(Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "MathMagicMCP" / "mathmagic.lock")))


class LockBusy(RuntimeError):
    def __init__(self, owner: dict):
        super().__init__("Another MathMagic MCP operation is running: " + json.dumps(owner, ensure_ascii=False))
        self.owner = owner


def _owner() -> dict:
    try:
        return json.loads(LOCK_PATH.with_suffix(".owner").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


@contextmanager
def exclusive(op: str, timeout: float = 10.0, path: Path | None = None):
    path = path or LOCK_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT)
    acquired = False
    try:
        end = time.monotonic() + timeout
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    os.lseek(fd, 0, 0)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError:
                if time.monotonic() >= end:
                    raise LockBusy(_owner())
                time.sleep(0.1)
        try:
            path.with_suffix(".owner").write_text(json.dumps(
                {"pid": os.getpid(), "op": op, "since": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
        except OSError:
            pass
        yield
    finally:
        if acquired:
            try:
                if os.name == "nt":
                    import msvcrt
                    os.lseek(fd, 0, 0)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
        os.close(fd)
