"""LLM decision protocol — structured meta-instructions from LLM responses."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class NextAction(BaseModel):
    title: str
    description: str = ""


class ToolCall(BaseModel):
    tool: str
    args: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_llm(cls, data: dict) -> "ToolCall":
        """Create ToolCall from LLM output, accepting both 'tool'/'args' and 'name'/'parameters' formats."""
        tool = data.get("tool") or data.get("name", "")
        args = data.get("args") or data.get("parameters", {})
        return cls(tool=tool, args=args)


class Reflection(BaseModel):
    progress: str = ""
    effectiveness: str = ""
    recommendation: str = ""
    should_continue: bool = True


# ── Planning & Cognitive Scaffold Models ──


class Subtask(BaseModel):
    """A single subtask in a task decomposition plan."""
    id: int
    title: str
    description: str = ""
    success_criteria: str = ""
    suggested_tools: List[str] = Field(default_factory=list)
    estimated_steps: int = 3
    status: str = "pending"       # pending | in_progress | completed | skipped
    result_summary: str = ""


class TaskPlan(BaseModel):
    """Structured plan produced by the planning phase."""
    subtasks: List[Subtask] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    overall_strategy: str = ""
    created_at_step: int = 0
    revision_count: int = 0


class HelpRequest(BaseModel):
    """Structured help/escalation request from LLM."""
    missing_information: List[str] = Field(default_factory=list)
    attempted_approaches: List[str] = Field(default_factory=list)
    specific_question: str = ""
    suggested_human_actions: List[str] = Field(default_factory=list)


class WorkingMemory(BaseModel):
    """LLM-generated compressed situation report."""
    summary: str = ""
    key_findings: List[str] = Field(default_factory=list)
    failed_approaches: List[str] = Field(default_factory=list)
    open_questions: List[str] = Field(default_factory=list)
    last_updated_step: int = 0


class TokenUsage(BaseModel):
    """Token usage from a single LLM call."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str = ""


class LLMResponse(BaseModel):
    """Structured response from an LLM call, including usage metadata."""
    content: str
    usage: TokenUsage = Field(default_factory=TokenUsage)


class LLMDecision(BaseModel):
    """Structured decision block parsed from LLM response."""
    next_action: Optional[NextAction] = None
    tool_calls: List[ToolCall] = Field(default_factory=list)
    human_required: bool = False
    human_reason: Optional[str] = None
    options: List[str] = Field(default_factory=list)
    task_complete: bool = False
    confidence: float = 0.5
    reflection: Optional[str] = None
    # Cognitive scaffold extensions
    help_request: Optional[HelpRequest] = None
    subtask_complete: bool = False
    plan_revision: Optional[TaskPlan] = None
