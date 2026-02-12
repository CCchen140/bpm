import os
import sys
from contextlib import contextmanager
from typing import Iterator


@contextmanager
def suppress_stderr_fd(enabled: bool = True) -> Iterator[None]:
    if not enabled:
        yield
        return

    try:
        stderr_fd = sys.stderr.fileno()
    except Exception:
        yield
        return

    try:
        saved_fd = os.dup(stderr_fd)
    except Exception:
        yield
        return

    try:
        with open(os.devnull, "w") as devnull:
            os.dup2(devnull.fileno(), stderr_fd)
            yield
    finally:
        try:
            try:
                os.dup2(saved_fd, stderr_fd)
            except Exception:
                pass
        finally:
            try:
                os.close(saved_fd)
            except Exception:
                pass
