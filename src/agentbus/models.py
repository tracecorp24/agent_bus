"""Agent Bus veri modelleri ve durum makinesi."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List, Dict, Any
import json


def utc_now_iso() -> str:
    """ISO-8601 UTC Z formatında şimdiki zamanı döndürür."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class JobStatus(str, Enum):
    QUEUED = "queued"
    BLOCKED = "blocked"
    RUNNING = "running"
    NEEDS_INPUT = "needs_input"
    ATTACH_PENDING = "attach_pending"
    HUMAN_ATTACHED = "human_attached"
    AWAITING_REVIEW = "awaiting_review"
    INTEGRATED = "integrated"
    PROMOTED = "promoted"
    CONFLICT = "conflict"
    TESTS_FAILED = "tests_failed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    CANCELLED = "cancelled"
    PAUSED = "paused"
    REJECTED = "rejected"


class TurnKind(str, Enum):
    INITIAL = "initial"
    FOLLOWUP = "followup"
    RESUME = "resume"
    REVIEW = "review"


class TurnStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class InvalidTransitionError(Exception):
    """Geçersiz durum geçişi hatası."""
    def __init__(self, job_id: str, from_status: str, to_status: str, reason: str = ""):
        self.job_id = job_id
        self.from_status = from_status
        self.to_status = to_status
        self.reason = reason
        super().__init__(
            f"İş [{job_id}] için geçersiz durum geçişi: '{from_status}' -> '{to_status}'. Neden: {reason}"
        )


# İzin verilen durum geçiş haritası
ALLOWED_TRANSITIONS: Dict[JobStatus, List[JobStatus]] = {
    JobStatus.QUEUED: [
        JobStatus.BLOCKED,
        JobStatus.RUNNING,
        JobStatus.PAUSED,
        JobStatus.CANCELLED,
        JobStatus.HUMAN_ATTACHED,
    ],
    JobStatus.BLOCKED: [
        JobStatus.QUEUED,
        JobStatus.CANCELLED,
        JobStatus.PAUSED,
    ],
    JobStatus.RUNNING: [
        JobStatus.AWAITING_REVIEW,
        JobStatus.NEEDS_INPUT,
        JobStatus.ATTACH_PENDING,
        JobStatus.HUMAN_ATTACHED,
        JobStatus.INTERRUPTED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
        JobStatus.PAUSED,
    ],
    JobStatus.ATTACH_PENDING: [
        JobStatus.HUMAN_ATTACHED,
        JobStatus.RUNNING,
        JobStatus.CANCELLED,
    ],
    JobStatus.HUMAN_ATTACHED: [
        JobStatus.QUEUED,
        JobStatus.AWAITING_REVIEW,
        JobStatus.CANCELLED,
    ],
    JobStatus.NEEDS_INPUT: [
        JobStatus.QUEUED,
        JobStatus.HUMAN_ATTACHED,
        JobStatus.CANCELLED,
    ],
    JobStatus.AWAITING_REVIEW: [
        JobStatus.INTEGRATED,
        JobStatus.CONFLICT,
        JobStatus.TESTS_FAILED,
        JobStatus.REJECTED,
        JobStatus.QUEUED,  # Düzeltme turu talimatı verilince
        JobStatus.HUMAN_ATTACHED,
        JobStatus.CANCELLED,
    ],
    JobStatus.INTEGRATED: [
        JobStatus.PROMOTED,
        JobStatus.CONFLICT,
        JobStatus.TESTS_FAILED,
        JobStatus.CANCELLED,
    ],
    JobStatus.CONFLICT: [
        JobStatus.QUEUED,
        JobStatus.CANCELLED,
    ],
    JobStatus.TESTS_FAILED: [
        JobStatus.QUEUED,
        JobStatus.CANCELLED,
    ],
    JobStatus.INTERRUPTED: [
        JobStatus.QUEUED,
        JobStatus.CANCELLED,
    ],
    JobStatus.PAUSED: [
        JobStatus.QUEUED,
        JobStatus.CANCELLED,
    ],
    JobStatus.FAILED: [
        JobStatus.QUEUED,  # Retry yapıldığında
        JobStatus.HUMAN_ATTACHED,
        JobStatus.CANCELLED,
    ],
    JobStatus.REJECTED: [
        JobStatus.QUEUED,  # Tekrar kuyruğa alındığında
    ],
    JobStatus.PROMOTED: [],  # Uç durum
    JobStatus.CANCELLED: [],  # Uç durum
}


@dataclass
class Job:
    id: str
    title: str
    task_md: str
    parent_id: Optional[str] = None
    depends_on: List[str] = field(default_factory=list)
    status: JobStatus = JobStatus.QUEUED
    priority: int = 5
    agent_profile: str = "default"
    conversation_id: Optional[str] = None
    worktree_path: Optional[str] = None
    branch: Optional[str] = None
    base_commit: Optional[str] = None
    allowed_paths: List[str] = field(default_factory=list)
    attempt: int = 0
    max_attempts: int = 3
    lease_owner: Optional[str] = None
    lease_until: Optional[str] = None
    idempotency_key: Optional[str] = None
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    result_summary: Optional[str] = None
    error: Optional[str] = None
    repo: Optional[str] = None


@dataclass
class Turn:
    id: Optional[int] = None
    job_id: str = ""
    seq: int = 1
    kind: TurnKind = TurnKind.INITIAL
    prompt: str = ""
    status: TurnStatus = TurnStatus.PENDING
    response: Optional[str] = None
    usage_json: Optional[str] = None
    duration_s: Optional[float] = None
    raw_path: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    pid: Optional[int] = None
    process_create_time: Optional[float] = None


@dataclass
class Event:
    id: Optional[int] = None
    ts: str = field(default_factory=utc_now_iso)
    job_id: Optional[str] = None
    agent_id: Optional[str] = None
    type: str = "info"
    level: str = "info"
    payload_json: str = "{}"


@dataclass
class Message:
    id: Optional[int] = None
    ts: str = field(default_factory=utc_now_iso)
    from_id: str = ""
    to_id: str = ""
    body: str = ""
    read_at: Optional[str] = None
    reply_to: Optional[int] = None


@dataclass
class BoardEntry:
    key: str
    value: str
    author: str
    updated_at: str = field(default_factory=utc_now_iso)
    version: int = 1


@dataclass
class Claim:
    path_glob: str
    job_id: str
    created_at: str = field(default_factory=utc_now_iso)


@dataclass
class AgentWorker:
    id: str
    pid: int
    host: str
    started_at: str = field(default_factory=utc_now_iso)
    heartbeat_at: str = field(default_factory=utc_now_iso)
    current_job: Optional[str] = None
