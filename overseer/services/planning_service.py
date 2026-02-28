"""Planning service — task decomposition, subtask lifecycle, and checkpoint reflection."""

from __future__ import annotations

import copy
import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import object_session

from overseer.core.protocols import Subtask, TaskPlan
from overseer.models.cognitive_object import CognitiveObject
from overseer.services.context_service import ContextService
from overseer.services.llm_service import LLMService

logger = logging.getLogger(__name__)


class PlanningService:
    """Handles task decomposition, subtask lifecycle, and checkpoint reflection."""

    def __init__(self, llm_service: LLMService, context_service: ContextService):
        self.llm = llm_service
        self.ctx = context_service

    async def generate_plan(
        self,
        co: CognitiveObject,
        memories: list[str],
        available_tools: list[dict],
    ) -> Optional[TaskPlan]:
        """Phase 1: Ask LLM to decompose the task into subtasks.

        Returns a TaskPlan or None if planning fails.
        """
        tool_names = [t.get("name", "") for t in available_tools]
        tool_list = ", ".join(tool_names) if tool_names else "No tools available"

        prompt = (
            f"## Goal\n{co.title}\n\n"
            f"## Description\n{co.description or 'N/A'}\n\n"
            f"## Available Tools\n{tool_list}\n"
        )
        if memories:
            prompt += "\n## Relevant Memories\n" + "\n".join(f"- {m}" for m in memories) + "\n"

        prompt += "\nPlease decompose this goal into an executable subtask plan."

        try:
            response = await self.llm.plan(prompt)
            plan = self.llm.parse_plan(response)
            if plan and plan.subtasks:
                ctx = copy.deepcopy(co.context or {})
                step_count = ctx.get("step_count", 0)
                plan.created_at_step = step_count
                return plan
            logger.warning("LLM returned empty or unparseable plan")
        except Exception as e:
            logger.error("Plan generation failed: %s", e)

        return None

    def store_plan(self, co: CognitiveObject, plan: TaskPlan) -> None:
        """Persist plan into co.context['plan'] and activate the first subtask."""
        ctx = copy.deepcopy(co.context or {})
        plan_dict = plan.model_dump()
        # Set first subtask as in_progress
        if plan_dict.get("subtasks"):
            plan_dict["subtasks"][0]["status"] = "in_progress"
            ctx["current_subtask_id"] = plan_dict["subtasks"][0]["id"]
        ctx["plan"] = plan_dict
        ctx["execution_phase"] = "executing"
        co.context = ctx
        (object_session(co) or self.ctx.session).commit()

    def get_current_subtask(self, co: CognitiveObject) -> Optional[Subtask]:
        """Return the currently active subtask from the plan."""
        ctx = co.context or {}
        plan = ctx.get("plan")
        if not plan:
            return None
        current_id = ctx.get("current_subtask_id")
        if current_id is None:
            return None
        for st_data in plan.get("subtasks", []):
            if st_data.get("id") == current_id and st_data.get("status") == "in_progress":
                return Subtask(**st_data)
        return None

    def advance_subtask(
        self, co: CognitiveObject, result_summary: str = ""
    ) -> Optional[Subtask]:
        """Mark current subtask as completed and move to the next one.

        Returns the new current subtask, or None if all are done.
        """
        ctx = copy.deepcopy(co.context or {})
        plan = ctx.get("plan")
        if not plan:
            return None

        current_id = ctx.get("current_subtask_id")
        subtasks = plan.get("subtasks", [])
        next_subtask = None

        for i, st in enumerate(subtasks):
            if st.get("id") == current_id:
                st["status"] = "completed"
                st["result_summary"] = result_summary
                # Find next pending subtask
                for j in range(i + 1, len(subtasks)):
                    if subtasks[j].get("status") == "pending":
                        subtasks[j]["status"] = "in_progress"
                        next_subtask = Subtask(**subtasks[j])
                        ctx["current_subtask_id"] = subtasks[j]["id"]
                        break
                break

        if next_subtask is None:
            ctx["current_subtask_id"] = None

        ctx["plan"] = plan
        co.context = ctx
        (object_session(co) or self.ctx.session).commit()
        return next_subtask

    def skip_subtask(
        self, co: CognitiveObject, reason: str = ""
    ) -> Optional[Subtask]:
        """Skip the current subtask and move to the next one."""
        ctx = copy.deepcopy(co.context or {})
        plan = ctx.get("plan")
        if not plan:
            return None

        current_id = ctx.get("current_subtask_id")
        subtasks = plan.get("subtasks", [])
        next_subtask = None

        for i, st in enumerate(subtasks):
            if st.get("id") == current_id:
                st["status"] = "skipped"
                st["result_summary"] = f"Skipped: {reason}"
                for j in range(i + 1, len(subtasks)):
                    if subtasks[j].get("status") == "pending":
                        subtasks[j]["status"] = "in_progress"
                        next_subtask = Subtask(**subtasks[j])
                        ctx["current_subtask_id"] = subtasks[j]["id"]
                        break
                break

        if next_subtask is None:
            ctx["current_subtask_id"] = None

        ctx["plan"] = plan
        co.context = ctx
        (object_session(co) or self.ctx.session).commit()
        return next_subtask

    def all_subtasks_done(self, co: CognitiveObject) -> bool:
        """Check if all subtasks are completed or skipped."""
        ctx = co.context or {}
        plan = ctx.get("plan")
        if not plan:
            return True  # no plan = nothing to check
        for st in plan.get("subtasks", []):
            if st.get("status") in ("pending", "in_progress"):
                return False
        return True

    def get_plan_progress_text(self, co: CognitiveObject) -> str:
        """Return a compact progress summary of the plan."""
        ctx = co.context or {}
        plan = ctx.get("plan")
        if not plan:
            return ""
        subtasks = plan.get("subtasks", [])
        total = len(subtasks)
        completed = sum(1 for st in subtasks if st.get("status") == "completed")
        skipped = sum(1 for st in subtasks if st.get("status") == "skipped")
        return f"Plan progress: {completed} completed, {skipped} skipped, {total - completed - skipped} remaining (total {total})"

    async def checkpoint_reflect(
        self, co: CognitiveObject
    ) -> Optional[TaskPlan]:
        """At subtask boundary, ask LLM to review progress and optionally revise plan.

        Returns a revised TaskPlan if the LLM decides to revise, otherwise None.
        """
        ctx = co.context or {}
        plan = ctx.get("plan", {})
        working_mem = ctx.get("working_memory", {})

        # Build a compact checkpoint prompt
        subtask_lines = []
        for st in plan.get("subtasks", []):
            status = st.get("status", "pending")
            title = st.get("title", "")
            summary = st.get("result_summary", "")
            line = f"- [{status}] {title}"
            if summary:
                line += f" → {summary}"
            subtask_lines.append(line)

        prompt = (
            f"## Goal\n{ctx.get('goal', co.title)}\n\n"
            f"## Plan Status\n{chr(10).join(subtask_lines)}\n\n"
            f"## Overall Strategy\n{plan.get('overall_strategy', 'N/A')}\n"
        )
        if working_mem:
            prompt += f"\n## Working Memory Summary\n{working_mem.get('summary', 'N/A')}\n"

        prompt += "\nPlease assess progress and decide if the plan needs revision."

        try:
            response = await self.llm.checkpoint(prompt)
            result = self.llm.parse_checkpoint(response)

            if not result.get("plan_still_valid", True) and result.get("revision"):
                # Apply revision
                revised_plan = TaskPlan(**result["revision"]) if isinstance(result["revision"], dict) else None
                if revised_plan:
                    ctx = copy.deepcopy(co.context or {})
                    old_plan = ctx.get("plan", {})
                    revised_dict = revised_plan.model_dump()
                    revised_dict["revision_count"] = old_plan.get("revision_count", 0) + 1
                    revised_dict["created_at_step"] = old_plan.get("created_at_step", 0)
                    ctx["plan"] = revised_dict
                    # Find and activate the first pending subtask
                    for st in revised_dict.get("subtasks", []):
                        if st.get("status") == "pending":
                            st["status"] = "in_progress"
                            ctx["current_subtask_id"] = st["id"]
                            break
                    co.context = ctx
                    (object_session(co) or self.ctx.session).commit()
                    logger.info("Plan revised at checkpoint for CO %s", co.id[:8])
                    return revised_plan

            # Log the assessment even if plan wasn't revised
            assessment = result.get("progress_assessment", "")
            if assessment:
                logger.info("Checkpoint assessment for CO %s: %s", co.id[:8], assessment)

        except Exception as e:
            logger.warning("Checkpoint reflection failed: %s", e)

        return None

    def get_subtask_tools(
        self, subtask: Subtask, all_tools: list[dict]
    ) -> list[dict]:
        """Return filtered tool list relevant to current subtask."""
        if not subtask.suggested_tools:
            return all_tools
        suggested = []
        for t in all_tools:
            if t.get("name", "") in subtask.suggested_tools:
                suggested.append(t)
        return suggested if suggested else all_tools
