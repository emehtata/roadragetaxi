"""Exit when the parent process is gone: the server when the Godot client
dies (crash, kill), a map-build worker when the server does. Neither can
rely on being told - a killed process runs no cleanup."""
import os
import sys
import threading
import time
from typing import Optional

POLL_S = 1.0


def is_alive(pid: int) -> bool:
    if sys.platform.startswith("win"):
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not handle:
            return False
        try:
            result = kernel32.WaitForSingleObject(handle, 0)
            if result == 0:  # WAIT_OBJECT_0
                return False
            if result == 258:  # WAIT_TIMEOUT
                return True
            if result == 0xFFFFFFFF:  # WAIT_FAILED
                raise ctypes.WinError(ctypes.get_last_error())
            raise OSError(f"Unexpected WaitForSingleObject result: {result}")
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)  # POSIX only: on Windows os.kill terminates
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def exit_with_parent(pid: Optional[int] = None) -> None:
    """A daemon thread ends this process (no cleanup) once `pid` (default:
    the current parent) has exited. Also a ProcessPoolExecutor initializer."""
    pid = pid or os.getppid()

    def watch() -> None:
        while is_alive(pid):
            time.sleep(POLL_S)
        os._exit(0)

    threading.Thread(target=watch, name="parent-watch", daemon=True).start()
