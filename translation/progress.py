"""Live progress on the terminal: steps with elapsed time, spend and a heartbeat."""

import sys
import threading
import time
from contextlib import contextmanager
from typing import Callable


def fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m{seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


class Progress:
    def __init__(self, cost: Callable[[], float] = lambda: 0.0, heartbeat_seconds: float = 30.0, stream=None):
        self.cost = cost
        self.heartbeat_seconds = heartbeat_seconds
        self.stream = stream or sys.stdout
        self.started = time.monotonic()

    def say(self, message: str) -> None:
        print(f"{time.strftime('%H:%M:%S')}  {message}", file=self.stream, flush=True)

    @contextmanager
    def step(self, label: str):
        """Print the step, a heartbeat while it runs, and its duration and cost when done."""
        start, cost_before = time.monotonic(), self.cost()
        self.say(f"   … {label}")
        done = threading.Event()

        def heartbeat():
            while not done.wait(self.heartbeat_seconds):
                self.say(f"     still working on {label} ({fmt_duration(time.monotonic() - start)})")

        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            yield
        finally:
            done.set()
            thread.join()
        self.say(f"   ✓ {label} ({fmt_duration(time.monotonic() - start)}, "
                 f"${self.cost() - cost_before:,.2f})")

    def elapsed(self) -> str:
        return fmt_duration(time.monotonic() - self.started)
