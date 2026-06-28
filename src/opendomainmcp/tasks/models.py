from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

JOB_QUEUED = "queued"
JOB_RUNNING = "running"
JOB_DONE = "done"
JOB_ERROR = "error"
JOB_CANCELLED = "cancelled"

JOB_STATUSES = {
    JOB_QUEUED,
    JOB_RUNNING,
    JOB_DONE,
    JOB_ERROR,
    JOB_CANCELLED,
}
ACTIVE_STATUSES = {JOB_QUEUED, JOB_RUNNING}
TERMINAL_STATUSES = {JOB_DONE, JOB_ERROR, JOB_CANCELLED}
RETRYABLE_TERMINAL_STATUSES = {JOB_ERROR, JOB_CANCELLED}

# Backwards-compatible alias for older imports.
TERMINAL = TERMINAL_STATUSES


def validate_task_status(status: str) -> str:
    if status not in JOB_STATUSES:
        raise ValueError(f"unknown task status: {status}")
    return status


@dataclass
class Task:
    id: str
    type: str               # ingest | synthesize | extract
    title: str
    collection: str
    status: str = "queued"  # queued | running | done | error | cancelled
    created_at: float = 0.0
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    total: int = 0
    done: int = 0
    failures: list = field(default_factory=list)   # [{"name","status"}]
    cancel_requested: bool = False
    error: Optional[str] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    result: Optional[dict] = None
    params: dict = field(default_factory=dict)
    attempts: int = 0
    recovered_at: Optional[float] = None
    recovery_count: int = 0
    last_transition: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        known = {f: d[f] for f in cls.__dataclass_fields__ if f in d}
        task = cls(**known)
        validate_task_status(task.status)
        return task

    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


def derive_child_status(index: int, done: int, running: bool,
                        failure: Optional[str]) -> str:
    if failure is not None:
        return failure
    if index < done:
        return "done"
    if index == done and running:
        return "running"
    return "pending"
