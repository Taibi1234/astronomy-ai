"""Process-local job manager for the recovery experiment.

One worker, one job at a time. Status is kept in memory and mirrored to disk by
the experiment itself, so a restart loses the *running* flag but never the
artifacts. A lock prevents duplicate concurrent runs.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from .experiment import run_experiment

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class JobManager:
    def __init__(self, out_dir: Path | None = None) -> None:
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="phase10")
        self._out_dir = out_dir
        self._status = {
            "status": "not_run",
            "mode": None,
            "progress": 0.0,
            "trials_done": 0,
            "trials_total": 0,
            "started_at": None,
            "finished_at": None,
            "error": None,
            "job_id": None,
        }

    def status(self) -> dict:
        with self._lock:
            return dict(self._status)

    def start(self, mode: str) -> tuple[bool, dict]:
        with self._lock:
            if self._status["status"] == "running":
                return False, dict(self._status)
            job_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            self._status.update(
                {
                    "status": "running",
                    "mode": mode,
                    "progress": 0.0,
                    "trials_done": 0,
                    "trials_total": 0,
                    "started_at": _now(),
                    "finished_at": None,
                    "error": None,
                    "job_id": job_id,
                }
            )
        self._executor.submit(self._run, mode)
        return True, self.status()

    def _progress(self, done: int, total: int) -> None:
        with self._lock:
            if self._status["status"] != "running":
                return
            self._status["trials_done"] = done
            self._status["trials_total"] = total
            self._status["progress"] = round(done / total, 4) if total else 0.0

    def _run(self, mode: str) -> None:
        try:
            run_experiment(mode, self._out_dir, progress=self._progress)
            with self._lock:
                self._status.update(
                    {
                        "status": "completed",
                        "progress": 1.0,
                        "finished_at": _now(),
                    }
                )
        except Exception as exc:  # noqa: BLE001 - surface any failure, keep old artifacts
            logger.exception("recovery experiment failed")
            with self._lock:
                self._status.update(
                    {
                        "status": "failed",
                        "finished_at": _now(),
                        "error": (
                            f"{type(exc).__name__}: experiment failed; "
                            "details are in the server log"
                        ),
                    }
                )

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


manager = JobManager()
