"""Kernel package — the irreplaceable core of the AI action firewall.

The kernel contains three components that define the system's identity:
- FirewallEngine: All security decisions (permissions, sandboxing, circuit-breaking)
- HumanGate: The human-in-the-loop communication channel
- PerceptionBus: Signal collection and statistics (no judgement)

If you remove the kernel, the system is no longer a firewall.
"""

from retro_cogos.kernel.perception_bus import PerceptionBus, PerceptionStats
from retro_cogos.kernel.human_gate import HumanGate, Intent, ApprovalResult
from retro_cogos.kernel.firewall_engine import FirewallEngine, FirewallVerdict
from retro_cogos.kernel.registry import PluginRegistry

__all__ = [
    "PerceptionBus",
    "PerceptionStats",
    "HumanGate",
    "Intent",
    "ApprovalResult",
    "FirewallEngine",
    "FirewallVerdict",
    "PluginRegistry",
]
