"""PerceptionBus — pure signal recorder for the firewall kernel.

Collects, classifies, and computes statistics. Makes NO judgements.
All decisions based on these statistics are made by FirewallEngine.

Sources extracted from:
- ExecutionService._record_approval()       → record_approval()
- ExecutionService._detect_no_progress()     → record_stagnation()
- ExecutionService.run_loop (inline)         → record_confidence()
- ContextService.classify_tool_result()      → classify_result()
- ContextService.merge_tool_result() (diff)  → detect_repeat()
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class PerceptionStats:
    """Read-only statistics snapshot consumed by FirewallEngine."""

    # Per-tool approval tracking
    approval_counts: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    reject_counts: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    consecutive_rejects: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    approval_times: Dict[str, List[float]] = field(default_factory=lambda: defaultdict(list))

    # Confidence sliding window
    confidence_window: List[float] = field(default_factory=list)

    # Stagnation tracking
    stagnation_count: int = 0

    def approval_rate(self, tool: str) -> float:
        """Return approval rate for a tool (0.0 to 1.0)."""
        total = self.approval_counts[tool] + self.reject_counts[tool]
        if total == 0:
            return 1.0
        return self.approval_counts[tool] / total

    def avg_hesitation(self, tool: str) -> float:
        """Return average approval time in seconds for a tool."""
        times = self.approval_times[tool]
        if not times:
            return 0.0
        return sum(times) / len(times)


class PerceptionBus:
    """Pure signal recorder. Only collects, only computes statistics, never judges.

    FirewallEngine reads get_stats() to make security decisions.
    """

    def __init__(self) -> None:
        self._stats = PerceptionStats()
        # Phase 2: Track last tool outputs for diff detection
        self._last_tool_outputs: Dict[str, str] = {}

    # ── Recording ──

    def record_approval(self, tool: str, approved: bool, elapsed: float) -> None:
        """Record an approval/rejection event for a tool."""
        if approved:
            self._stats.approval_counts[tool] += 1
            self._stats.consecutive_rejects[tool] = 0
        else:
            self._stats.reject_counts[tool] += 1
            self._stats.consecutive_rejects[tool] += 1
        self._stats.approval_times[tool].append(elapsed)
        logger.debug(
            "Perception: %s %s (%.1fs), consecutive_rejects=%d",
            tool,
            "approved" if approved else "rejected",
            elapsed,
            self._stats.consecutive_rejects[tool],
        )

    def record_confidence(self, confidence: float) -> None:
        """Record a confidence value from an LLM decision."""
        self._stats.confidence_window.append(confidence)
        # Keep a sliding window of last 10 values
        if len(self._stats.confidence_window) > 10:
            self._stats.confidence_window = self._stats.confidence_window[-10:]

    def record_stagnation(self, reflection: str) -> None:
        """Record a stagnation signal detected in reflection text."""
        self._stats.stagnation_count += 1
        logger.debug("Perception: stagnation recorded (total=%d): %s",
                      self._stats.stagnation_count, reflection[:80])

    # ── Classification ──

    @staticmethod
    def classify_result(tool: str, result: dict) -> str:
        """Classify a tool result into a semantic category.

        Returns one of: 'success', 'error', 'empty', 'partial'.

        Extracted from ContextService.classify_tool_result().
        """
        status = result.get("status", "")
        if status == "error":
            return "error"
        if status == "ok":
            output = result.get("output", result.get("content", ""))
            if not output or str(output).strip() == "":
                return "empty"
            return "success"
        # Fallback: check for error indicators in string representation
        result_str = json.dumps(result, ensure_ascii=False)
        if '"error"' in result_str or '"status": "error"' in result_str:
            return "error"
        return "partial"

    def detect_repeat(self, tool: str, result: str,
                      tool_args: Optional[dict] = None) -> Optional[str]:
        """Detect if a tool returned the same output as last time.

        Returns a diff note string ("[SAME ...]" or "[CHANGED ...]"), or None if first call.

        Extracted from ContextService.merge_tool_result() diff logic.
        """
        if tool_args:
            tool_key = f"{tool}:{json.dumps(tool_args, sort_keys=True, ensure_ascii=False)}"
        else:
            tool_key = tool

        prev_output = self._last_tool_outputs.get(tool_key)
        self._last_tool_outputs[tool_key] = result

        if prev_output is None:
            return None
        if result == prev_output:
            return " [SAME as previous call — no new information]"
        return " [CHANGED from previous call]"

    # ── Statistics (read by FirewallEngine) ──

    def get_stats(self) -> PerceptionStats:
        """Return current statistics snapshot."""
        return self._stats

    def reset_stats(self) -> None:
        """Reset all statistics to initial state."""
        self._stats = PerceptionStats()
        self._last_tool_outputs.clear()
        logger.info("PerceptionBus statistics reset")

    def get_tool_outputs_snapshot(self) -> Dict[str, str]:
        """Return current tool outputs state (for checkpoint serialization)."""
        return dict(self._last_tool_outputs)

    def restore_tool_outputs(self, outputs: Dict[str, str]) -> None:
        """Restore tool outputs state from checkpoint."""
        self._last_tool_outputs = dict(outputs)

    def build_approval_summary(self) -> str:
        """Generate a human-readable summary of approval statistics.

        Extracted from ExecutionService._build_approval_summary().
        """
        stats = self._stats
        all_tools = set(stats.approval_counts.keys()) | set(stats.reject_counts.keys())
        if not all_tools:
            return ""

        lines = []
        for tool in sorted(all_tools):
            approved = stats.approval_counts[tool]
            rejected = stats.reject_counts[tool]
            total = approved + rejected
            if total > 0:
                rate = approved / total
                lines.append(
                    f"  {tool}: {approved}/{total} approved ({rate:.0%})"
                )
        if not lines:
            return ""
        return "User approval patterns:\n" + "\n".join(lines)
