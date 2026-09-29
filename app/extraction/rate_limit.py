"""Shared process-wide request pacing for all vision providers."""
import os
import threading
import time


class RequestPacer:
    def __init__(self):
        self._lock = threading.Lock()
        self._next_request_at = 0.0

    def acquire(self):
        try:
            max_rpm = max(1, int(os.getenv("EXTRACTION_MAX_RPM", "4")))
        except ValueError:
            max_rpm = 4
        spacing = 60.0 / max_rpm + 0.05
        with self._lock:
            now = time.monotonic()
            request_at = max(now, self._next_request_at)
            self._next_request_at = request_at + spacing
        delay = request_at - time.monotonic()
        if delay > 0:
            time.sleep(delay)


request_pacer = RequestPacer()
