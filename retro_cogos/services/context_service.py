"""Context service — StateDict management, prompt building, context compression."""

from __future__ import annotations

import copy
import json
import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from sqlalchemy.orm import Session, object_session

from retro_cogos.database import get_session
from retro_cogos.models.cognitive_object import CognitiveObject
from retro_cogos.core.protocols import WorkingMemory

if TYPE_CHECKING:
    from retro_cogos.services.llm_service import LLMService

logger = logging.getLogger(__name__)


class ContextService:
    def __init__(self, session: Session | None = None):
        self._session = session
        # Phase 2: Track last tool outputs per tool name for diff detection
        self._last_tool_outputs: Dict[str, str] = {}

    def restore_tool_outputs(self, outputs: Dict[str, str]) -> None:
        """Restore last-tool-outputs state from checkpoint."""
        self._last_tool_outputs = outputs

    @property
    def session(self) -> Session:
        if self._session is None:
            self._session = get_session()
        return self._session

    def build_prompt(
        self,
        co: CognitiveObject,
        memories: list[str] | None = None,
        available_tools: list[dict] | None = None,
        elapsed_seconds: float = 0.0,
        max_steps: int = 0,
        constraint_hints: list[str] | None = None,
    ) -> str:
        """Build a complete prompt for the LLM from CO context + memories + tools."""
        ctx = co.context or {}
        goal = ctx.get("goal", co.title)
        findings = ctx.get("accumulated_findings", [])
        step_count = ctx.get("step_count", 0)
        pending = ctx.get("pending_questions", [])
        artifacts = ctx.get("artifacts_produced", [])
        last_reflection = ctx.get("last_reflection", None)
        working_mem = ctx.get("working_memory", None)
        plan = ctx.get("plan", None)
        current_subtask_id = ctx.get("current_subtask_id", None)

        parts = [f"## Goal\n{goal}"]

        if co.description:
            parts.append(f"\n## Description\n{co.description}")

        # Current subtask context (if planning is active)
        if plan and current_subtask_id is not None:
            subtasks = plan.get("subtasks", [])
            total = len(subtasks)
            current_st = None
            for st in subtasks:
                if st.get("id") == current_subtask_id:
                    current_st = st
                    break
            if current_st:
                parts.append(
                    f"\n## Current Subtask ({current_subtask_id} of {total})\n"
                    f"**{current_st.get('title', '')}**\n"
                    f"{current_st.get('description', '')}\n"
                    f"Success Criteria: {current_st.get('success_criteria', 'N/A')}"
                )

        # Phase 1: Resource awareness — let LLM know how much it has spent
        elapsed_min = elapsed_seconds / 60.0
        resource_lines = [
            f"- Steps completed: {step_count}",
            f"- Elapsed time: {elapsed_min:.1f} min",
        ]
        if max_steps > 0:
            remaining = max(0, max_steps - step_count)
            resource_lines.append(f"- Steps remaining: {remaining} (limit: {max_steps})")
            if remaining <= 5:
                resource_lines.append(
                    "- WARNING: approaching step limit, prioritize essential work"
                )
        parts.append("\n## Resource Status\n" + "\n".join(resource_lines))

        # Tool section: narrow by subtask suggestions if available
        if available_tools:
            suggested_tool_names: list[str] = []
            if plan and current_subtask_id is not None:
                for st in plan.get("subtasks", []):
                    if st.get("id") == current_subtask_id:
                        suggested_tool_names = st.get("suggested_tools", [])
                        break

            if suggested_tool_names:
                # Show suggested tools with full schema, others as compact list
                suggested = []
                others = []
                for t in available_tools:
                    name = t.get("name", "")
                    if name in suggested_tool_names:
                        suggested.append(t)
                    else:
                        others.append(t)

                tool_lines = self._format_tools_detailed(suggested)
                parts.append(f"\n## Suggested Tools (for this subtask)\n" + "\n".join(tool_lines))
                if others:
                    other_names = ", ".join(t.get("name", "") for t in others)
                    parts.append(f"\n## Other Available Tools\n{other_names}")
            else:
                tool_lines = self._format_tools_detailed(available_tools)
                parts.append(f"\n## Available Tools\n" + "\n".join(tool_lines))

        # Working memory (compressed history) or raw findings
        if working_mem:
            wm_parts = []
            if working_mem.get("summary"):
                wm_parts.append(f"Summary: {working_mem['summary']}")
            if working_mem.get("key_findings"):
                wm_parts.append("Key Findings:\n" + "\n".join(f"- {kf}" for kf in working_mem["key_findings"]))
            if working_mem.get("failed_approaches"):
                wm_parts.append("Failed Approaches:\n" + "\n".join(f"- {fa}" for fa in working_mem["failed_approaches"]))
            if working_mem.get("open_questions"):
                wm_parts.append("Open Questions:\n" + "\n".join(f"- {oq}" for oq in working_mem["open_questions"]))
            last_step = working_mem.get("last_updated_step", 0)
            parts.append(f"\n## Working Memory (compressed from steps 1-{last_step})\n" + "\n".join(wm_parts))

            # Show only recent findings (after compression point)
            recent = [f for f in findings if isinstance(f.get("step"), (int, float)) and f["step"] > last_step]
            if recent:
                recent_text = "\n".join(
                    f"- Step {f.get('step', '?')}: [{f.get('key', '')}] {f.get('value', '')}"
                    for f in recent
                )
                parts.append(f"\n## Recent Findings (steps {last_step + 1}-{step_count})\n{recent_text}")
        elif findings:
            findings_text = "\n".join(
                f"- Step {f.get('step', '?')}: [{f.get('key', '')}] {f.get('value', '')}"
                for f in findings
            )
            parts.append(f"\n## Accumulated Findings (Steps completed: {step_count})\n{findings_text}")

        # Pre-emptive constraint hints (from kernel if provided, else self-computed)
        constraints = constraint_hints if constraint_hints is not None else self.build_constraint_hints(co)
        if constraints:
            parts.append(f"\n## Constraints (DO NOT repeat these mistakes)\n" + "\n".join(f"- {c}" for c in constraints))

        if pending:
            parts.append(f"\n## Pending Questions\n" + "\n".join(f"- {q}" for q in pending))

        if artifacts:
            parts.append(f"\n## Artifacts Produced\n" + "\n".join(f"- {a}" for a in artifacts))

        if last_reflection:
            parts.append(f"\n## Last Reflection\n{last_reflection}")

        # Resume notice: prominently surface the resume signal if present
        resumed_findings = [
            f for f in findings
            if isinstance(f, dict) and f.get("key") == "system:resumed"
        ]
        if resumed_findings:
            parts.append(f"\n## Resume Notice\n{resumed_findings[-1].get('value', '')}")

        if memories:
            parts.append(f"\n## Relevant Memories from Past Events\n" + "\n".join(f"- {m}" for m in memories))

        parts.append(
            "\n## Instructions\n"
            "Based on the above context, decide the next step to take toward achieving the goal. "
            "If you need tools, specify them in tool_calls using the exact tool name from the Available Tools list. "
            "If you need human input, set human_required to true and explain why. "
            "If you lack critical information, use help_request to ask for help.\n"
            "当需要写入文件时，路径统一使用 \"output/\" 目录前缀（如 \"output/result.md\"）。"
            "不要将文件写入项目根目录或其他位置。"
        )

        return "\n".join(parts)

    @staticmethod
    def _format_tools_detailed(tools: list[dict]) -> list[str]:
        """Format a list of tools with full schema details."""
        tool_lines = []
        for t in tools:
            name = t.get("name", "")
            desc = t.get("description", "")
            params = t.get("parameters", {})
            props = params.get("properties", {})
            required = params.get("required", [])
            if props:
                param_parts = []
                for pname, pinfo in props.items():
                    ptype = pinfo.get("type", "string")
                    pdesc = pinfo.get("description", "")
                    req = " (required)" if pname in required else ""
                    param_parts.append(f"    - `{pname}` ({ptype}{req}): {pdesc}")
                params_text = "\n" + "\n".join(param_parts)
            else:
                params_text = ""
            tool_lines.append(f"- **{name}**: {desc}{params_text}")
        return tool_lines

    def merge_step_result(
        self, co: CognitiveObject, step_number: int, key: str, value: str
    ) -> Dict[str, Any]:
        """Merge a step result into the CO's StateDict."""
        ctx = copy.deepcopy(co.context or {})
        findings = list(ctx.get("accumulated_findings", []))
        findings.append({"step": step_number, "key": key, "value": value})
        ctx["accumulated_findings"] = findings
        ctx["step_count"] = step_number
        co.context = ctx
        # Commit on the session that owns the CO object
        sess = object_session(co) or self.session
        sess.commit()
        return ctx

    @staticmethod
    def classify_tool_result(result: dict) -> str:
        """Classify a tool result into a semantic category.

        Returns one of: 'success', 'error', 'empty', 'partial'.
        """
        status = result.get("status", "")
        if status == "error":
            return "error"
        if status == "ok":
            output = result.get("output", result.get("content", ""))
            if not output or output.strip() == "":
                return "empty"
            return "success"
        # Fallback: check for error indicators in string representation
        result_str = json.dumps(result, ensure_ascii=False)
        if '"error"' in result_str or '"status": "error"' in result_str:
            return "error"
        return "partial"

    def merge_tool_result(
        self, co: CognitiveObject, step_number: int, tool_name: str, result: str,
        raw_result: dict | None = None,
        tool_args: dict | None = None,
    ) -> Dict[str, Any]:
        """Merge a tool execution result into context with semantic classification."""
        # Phase 2: Classify the result
        classification = "success"
        if raw_result is not None:
            classification = self.classify_tool_result(raw_result)

        # Phase 2: Diff detection — compare with last output from same tool+args
        diff_note = ""
        if tool_args:
            tool_key = f"{tool_name}:{json.dumps(tool_args, sort_keys=True, ensure_ascii=False)}"
        else:
            tool_key = tool_name
        prev_output = self._last_tool_outputs.get(tool_key)
        if prev_output is not None:
            if result == prev_output:
                diff_note = " [SAME as previous call — no new information]"
            else:
                diff_note = " [CHANGED from previous call]"
        self._last_tool_outputs[tool_key] = result

        # Build enriched value with classification prefix
        prefix = f"[{classification}]"
        enriched_result = f"{prefix}{diff_note} {result}"

        return self.merge_step_result(
            co, step_number, f"tool:{tool_name}", enriched_result
        )

    def check_intent_deviation(
        self, intent_description: str, tool_results: list[dict],
    ) -> str | None:
        """Check if tool results deviate from the stated intent.

        Returns a deviation warning string, or None if results look aligned.
        """
        if not intent_description or not tool_results:
            return None

        all_errors = all(r.get("status") == "error" for r in tool_results)
        if all_errors:
            return (
                f"Intent was '{intent_description}', but all tool calls failed. "
                f"The current approach is not working."
            )

        all_empty = all(
            self.classify_tool_result(r) == "empty" for r in tool_results
        )
        if all_empty:
            return (
                f"Intent was '{intent_description}', but all tools returned empty results. "
                f"The data or resource may not exist."
            )

        # Case 3: Partial failure — some tools failed, some succeeded
        error_count = sum(1 for r in tool_results if r.get("status") == "error")
        if 0 < error_count < len(tool_results):
            failed = [r.get("tool", "?") for r in tool_results if r.get("status") == "error"]
            return (
                f"Intent was '{intent_description}', but {error_count}/{len(tool_results)} "
                f"tool calls failed ({', '.join(failed)}). Review partial results."
            )

        return None

    def merge_reflection(
        self, co: CognitiveObject, reflection: str
    ) -> Dict[str, Any]:
        """Store the latest reflection in context."""
        ctx = copy.deepcopy(co.context or {})
        ctx["last_reflection"] = reflection
        co.context = ctx
        sess = object_session(co) or self.session
        sess.commit()
        return ctx

    def add_artifact(self, co: CognitiveObject, artifact_path: str) -> None:
        """Record an artifact path in context."""
        ctx = copy.deepcopy(co.context or {})
        artifacts = list(ctx.get("artifacts_produced", []))
        artifacts.append(artifact_path)
        ctx["artifacts_produced"] = artifacts
        co.context = ctx
        sess = object_session(co) or self.session
        sess.commit()

    def compress_if_needed(self, co: CognitiveObject, max_chars: int = 16000) -> bool:
        """Compress early findings if context is too large (truncation fallback).

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

        ctx = copy.deepcopy(ctx)
        ctx["accumulated_findings"] = [compressed_finding] + keep
        co.context = ctx
        sess = object_session(co) or self.session
        sess.commit()
        logger.info("Compressed context for CO %s: %d findings → %d", co.id[:8], len(findings), len(ctx["accumulated_findings"]))
        return True

    def build_constraint_hints(self, co: CognitiveObject) -> List[str]:
        """Generate pre-emptive constraint warnings from past failures and user behavior.

        Sources:
        - working_memory.failed_approaches
        - accumulated_findings with [error] classification
        - accumulated_findings with perception:tool_avoidance signals
        """
        ctx = co.context or {}
        hints: List[str] = []

        # From working memory
        working_mem = ctx.get("working_memory")
        if working_mem and working_mem.get("failed_approaches"):
            for fa in working_mem["failed_approaches"]:
                hints.append(fa)

        # From recent findings: extract errors and avoidance signals
        findings = ctx.get("accumulated_findings", [])
        seen_errors: set[str] = set()
        for f in findings:
            value = f.get("value", "")
            key = f.get("key", "")
            # Error results
            if value.startswith("[error]") and key.startswith("tool:"):
                tool_name = key[5:]  # strip "tool:" prefix
                error_sig = f"{tool_name}:{value[:60]}"
                if error_sig not in seen_errors:
                    seen_errors.add(error_sig)
                    hints.append(f"Tool '{tool_name}' previously failed: {value[8:80]}...")
            # Tool avoidance signals from perception
            if key == "perception:tool_avoidance":
                hints.append(value)
            # Same-as-previous warnings
            if "[SAME as previous call" in value:
                tool_name = key[5:] if key.startswith("tool:") else key
                hints.append(f"Calling '{tool_name}' with the same args returned identical results. Try different parameters.")

        return hints[:10]  # cap to avoid prompt bloat

    async def compress_to_working_memory(
        self, co: CognitiveObject, llm_service: "LLMService"
    ) -> Optional[WorkingMemory]:
        """Use LLM to compress accumulated findings into a WorkingMemory summary.

        Called at subtask boundaries. Replaces raw findings with a structured
        summary while preserving recent findings.
        """
        ctx = co.context or {}
        findings = ctx.get("accumulated_findings", [])
        step_count = ctx.get("step_count", 0)

        if len(findings) < 4:
            return None  # not enough to compress

        # Build the compression prompt with full findings
        findings_text = "\n".join(
            f"- Step {f.get('step', '?')}: [{f.get('key', '')}] {f.get('value', '')}"
            for f in findings
        )
        goal = ctx.get("goal", co.title)
        prompt = (
            f"## Goal\n{goal}\n\n"
            f"## Execution History ({len(findings)} findings, {step_count} steps)\n"
            f"{findings_text}"
        )

        try:
            response = await llm_service.compress(prompt)
            wm = llm_service.parse_working_memory(response)
            if wm:
                wm.last_updated_step = step_count
                # Store working memory in context
                ctx = copy.deepcopy(co.context or {})
                ctx["working_memory"] = wm.model_dump()
                co.context = ctx
                sess = object_session(co) or self.session
                sess.commit()
                logger.info(
                    "Compressed context to working memory for CO %s at step %d",
                    co.id[:8], step_count,
                )
                return wm
        except Exception as e:
            logger.warning("LLM-based compression failed, will use fallback: %s", e)

        return None
