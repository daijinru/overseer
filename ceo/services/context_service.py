"""Context service — StateDict management, prompt building, context compression."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from sqlalchemy.orm import Session

from ceo.database import get_session
from ceo.models.cognitive_object import CognitiveObject

logger = logging.getLogger(__name__)


class ContextService:
    def __init__(self, session: Session | None = None):
        self._session = session

    @property
    def session(self) -> Session:
        if self._session is None:
            self._session = get_session()
        return self._session

    def build_prompt(self, co: CognitiveObject, memories: list[str] | None = None) -> str:
        """Build a complete prompt for the LLM from CO context + memories."""
        ctx = co.context or {}
        goal = ctx.get("goal", co.title)
        findings = ctx.get("accumulated_findings", [])
        step_count = ctx.get("step_count", 0)
        pending = ctx.get("pending_questions", [])
        artifacts = ctx.get("artifacts_produced", [])
        last_reflection = ctx.get("last_reflection", None)

        parts = [f"## Goal\n{goal}"]

        if co.description:
            parts.append(f"\n## Description\n{co.description}")

        if findings:
            findings_text = "\n".join(
                f"- Step {f.get('step', '?')}: [{f.get('key', '')}] {f.get('value', '')}"
                for f in findings
            )
            parts.append(f"\n## Accumulated Findings (Steps completed: {step_count})\n{findings_text}")

        if pending:
            parts.append(f"\n## Pending Questions\n" + "\n".join(f"- {q}" for q in pending))

        if artifacts:
            parts.append(f"\n## Artifacts Produced\n" + "\n".join(f"- {a}" for a in artifacts))

        if last_reflection:
            parts.append(f"\n## Last Reflection\n{last_reflection}")

        if memories:
            parts.append(f"\n## Relevant Memories from Past Events\n" + "\n".join(f"- {m}" for m in memories))

        parts.append(
            "\n## Instructions\n"
            "Based on the above context, decide the next step to take toward achieving the goal. "
            "If you need tools, specify them in tool_calls. "
            "If you need human input, set human_required to true and explain why."
        )

        return "\n".join(parts)

    def merge_step_result(
        self, co: CognitiveObject, step_number: int, key: str, value: str
    ) -> Dict[str, Any]:
        """Merge a step result into the CO's StateDict."""
        ctx = dict(co.context or {})
        findings = list(ctx.get("accumulated_findings", []))
        findings.append({"step": step_number, "key": key, "value": value})
        ctx["accumulated_findings"] = findings
        ctx["step_count"] = step_number
        co.context = ctx
        self.session.commit()
        return ctx

    def merge_tool_result(
        self, co: CognitiveObject, step_number: int, tool_name: str, result: str
    ) -> Dict[str, Any]:
        """Merge a tool execution result into context."""
        return self.merge_step_result(
            co, step_number, f"tool:{tool_name}", result
        )

    def merge_reflection(
        self, co: CognitiveObject, reflection: str
    ) -> Dict[str, Any]:
        """Store the latest reflection in context."""
        ctx = dict(co.context or {})
        ctx["last_reflection"] = reflection
        co.context = ctx
        self.session.commit()
        return ctx

    def add_artifact(self, co: CognitiveObject, artifact_path: str) -> None:
        """Record an artifact path in context."""
        ctx = dict(co.context or {})
        artifacts = list(ctx.get("artifacts_produced", []))
        artifacts.append(artifact_path)
        ctx["artifacts_produced"] = artifacts
        co.context = ctx
        self.session.commit()

    def compress_if_needed(self, co: CognitiveObject, max_chars: int = 16000) -> bool:
        """Compress early findings if context is too large.

        Returns True if compression was performed.
        """
        ctx = co.context or {}
        ctx_text = json.dumps(ctx, ensure_ascii=False)
        if len(ctx_text) <= max_chars:
            return False

        findings = list(ctx.get("accumulated_findings", []))
        if len(findings) <= 3:
            return False

        # Keep the last 3 findings in full, summarize earlier ones
        keep = findings[-3:]
        to_compress = findings[:-3]

        summary_parts = []
        for f in to_compress:
            summary_parts.append(f"Step {f.get('step', '?')}: {f.get('key', '')} = {f.get('value', '')[:80]}")

        compressed_finding = {
            "step": f"1-{to_compress[-1].get('step', '?')}",
            "key": "compressed_summary",
            "value": "; ".join(summary_parts),
        }

        ctx = dict(ctx)
        ctx["accumulated_findings"] = [compressed_finding] + keep
        co.context = ctx
        self.session.commit()
        logger.info("Compressed context for CO %s: %d findings → %d", co.id[:8], len(findings), len(ctx["accumulated_findings"]))
        return True
