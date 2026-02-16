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
