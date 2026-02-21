"""Status enumerations for CognitiveObject and Execution."""

from enum import Enum


class COStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    ABORTED = "aborted"
    FAILED = "failed"


class ExecutionStatus(str, Enum):
    PENDING = "pending"
    RUNNING_LLM = "running_llm"
    RUNNING_TOOL = "running_tool"
    AWAITING_HUMAN = "awaiting_human"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"
    FAILED = "failed"


class ToolPermission(str, Enum):
    AUTO = "auto"
    NOTIFY = "notify"
    CONFIRM = "confirm"
    APPROVE = "approve"
