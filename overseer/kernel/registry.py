"""PluginRegistry — replaces hardcoded service instantiation.

Manages plugin registration, retrieval, and lifecycle.
Replaces the hardcoded instantiation in ExecutionService.__init__.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Type, TypeVar

from overseer.config import AppConfig
from overseer.core.plugin_protocols import (
    ContextPlugin,
    LLMPlugin,
    MemoryPlugin,
    PlanPlugin,
    ToolPlugin,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


class PluginRegistry:
    """Plugin registration and retrieval.

    Replaces ExecutionService.__init__'s hardcoded Service instantiation.
    Plugins are registered by Protocol type and retrieved by the same type.
    """

    def __init__(self) -> None:
        self._plugins: Dict[type, Any] = {}

    def register(self, protocol_type: type, implementation: Any) -> None:
        """Register a plugin implementation for a Protocol type."""
        self._plugins[protocol_type] = implementation
        logger.debug("Registered plugin: %s → %s",
                      protocol_type.__name__,
                      type(implementation).__name__)

    def get(self, protocol_type: Type[T]) -> T:
        """Retrieve a registered plugin by Protocol type.

        Raises KeyError if the plugin is not registered.
        """
        if protocol_type not in self._plugins:
            raise KeyError(
                f"No plugin registered for {protocol_type.__name__}. "
                f"Registered: {[t.__name__ for t in self._plugins]}"
            )
        return self._plugins[protocol_type]

    def has(self, protocol_type: type) -> bool:
        """Check if a plugin is registered for the given Protocol type."""
        return protocol_type in self._plugins

    def list_registered(self) -> Dict[str, str]:
        """Return a mapping of registered Protocol names to implementation class names."""
        return {
            proto.__name__: type(impl).__name__
            for proto, impl in self._plugins.items()
        }

    @classmethod
    def create_default(
        cls,
        config: AppConfig,
        session: Optional[Any] = None,
    ) -> "PluginRegistry":
        """Create a registry with the current Service implementations as default plugins.

        This is the bridge between the old architecture and the new one:
        existing Services satisfy Plugin Protocols via structural subtyping.
        """
        from overseer.services.llm_service import LLMService
        from overseer.services.tool_service import ToolService
        from overseer.services.memory_service import MemoryService
        from overseer.services.context_service import ContextService
        from overseer.services.planning_service import PlanningService

        registry = cls()

        llm = LLMService()
        tool = ToolService()
        memory = MemoryService(session)
        context = ContextService(session)
        planning = PlanningService(llm, context)

        registry.register(LLMPlugin, llm)
        registry.register(ToolPlugin, tool)
        registry.register(MemoryPlugin, memory)
        registry.register(ContextPlugin, context)
        registry.register(PlanPlugin, planning)

        return registry
