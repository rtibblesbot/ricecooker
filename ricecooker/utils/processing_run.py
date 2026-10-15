import contextlib
import threading
from concurrent.futures import Future

_lock = threading.Lock()
_futures = None


@contextlib.contextmanager
def processing_run():
    """Scope ``run_once()``: placements of a copied node process concurrently and reach the same sources."""
    global _futures
    _futures = {}
    try:
        yield
    finally:
        _futures = None


def run_once(key, fn, reraise=True):
    """Return ``fn()``; within a ``processing_run()``, later calls with ``key`` wait for its result.

    Its exception is re-raised to every caller, or returns None to those passing ``reraise=False``.
    """
    if _futures is None:
        return fn()
    with _lock:
        future = _futures.get(key)
        owner = future is None
        if owner:
            future = _futures[key] = Future()
    if owner:
        try:
            future.set_result(fn())
        except BaseException as err:
            future.set_exception(err)
    if not reraise and future.exception() is not None:
        return None
    return future.result()
