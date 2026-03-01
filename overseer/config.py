"""YAML configuration loading with Pydantic validation."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import yaml
from pydantic import BaseModel, Field


def _default_data_dir() -> Path:
    """Return the default data directory: ~/.overseer"""
    return Path.home() / ".overseer"


class ModelEndpoint(BaseModel):
    """Configuration for a single model endpoint."""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o"
    api_key: str = "sk-placeholder"
    max_tokens: int = 4096
    temperature: float = 0.7


class LLMConfig(BaseModel):
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o"
    api_key: str = "sk-placeholder"
    max_tokens: int = 4096
    temperature: float = 0.7
    max_retries: int = 3
    retry_base_delay: float = 1.0   # seconds
    retry_max_delay: float = 60.0   # seconds

    # Multi-model routing (optional, backward compatible)
    primary: Optional[ModelEndpoint] = None
    secondary: Optional[ModelEndpoint] = None

    def get_primary(self) -> ModelEndpoint:
        """Return the primary model config, falling back to top-level fields."""
        if self.primary:
            return self.primary
        return ModelEndpoint(
            base_url=self.base_url,
            model=self.model,
            api_key=self.api_key,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )

    def get_secondary(self) -> ModelEndpoint:
        """Return the secondary model config, falling back to primary."""
        if self.secondary:
            return self.secondary
        return self.get_primary()


class DatabaseConfig(BaseModel):
    path: str = str(_default_data_dir() / "overseer_data.db")


class MCPServerConfig(BaseModel):
    """Configuration for a single MCP server."""
    transport: str = "stdio"  # "stdio", "sse", or "streamable_http"
    command: Optional[str] = None  # for stdio transport
    args: List[str] = Field(default_factory=list)  # for stdio transport
    env: Optional[Dict[str, str]] = None  # for stdio transport
    url: Optional[str] = None  # for sse / streamable_http transport
    headers: Optional[Dict[str, str]] = None  # for sse / streamable_http transport


class MCPConfig(BaseModel):
    """MCP (Model Context Protocol) client configuration."""
    servers: Dict[str, MCPServerConfig] = Field(default_factory=dict)


class ReflectionConfig(BaseModel):
    interval: int = 5
    similarity_threshold: float = 0.8


class ContextConfig(BaseModel):
    max_tokens: int = 8000
    output_dir: str = str(_default_data_dir() / "output")
    readable_paths: List[str] = Field(
        default_factory=lambda: ["output/", "."],
        description="Whitelist of directories for file_read without approval. "
        "Paths outside this list require human confirmation.",
    )


class PlanningConfig(BaseModel):
    enabled: bool = True
    max_subtasks: int = 10
    checkpoint_on_subtask_complete: bool = True
    compress_after_subtask: bool = True


class ExecutionConfig(BaseModel):
    max_steps: int = 50


class LogConfig(BaseModel):
    dir: str = str(_default_data_dir() / "logs")


class AppConfig(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    tool_permissions: Dict[str, str] = Field(default_factory=lambda: {"default": "confirm"})
    reflection: ReflectionConfig = Field(default_factory=ReflectionConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    planning: PlanningConfig = Field(default_factory=PlanningConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    log: LogConfig = Field(default_factory=LogConfig)


_config: AppConfig | None = None


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """Load config from YAML file. Falls back to defaults if file not found."""
    global _config
    if _config is not None:
        return _config

    paths_to_try = []
    if config_path:
        paths_to_try.append(Path(config_path))
    paths_to_try.extend([
        Path("config.yaml"),
        Path("config.yml"),
        Path.home() / ".overseer" / "config.yaml",
        Path.home() / ".overseer" / "config.yml",
    ])

    for p in paths_to_try:
        if p.exists():
            with open(p) as f:
                data = yaml.safe_load(f) or {}
            _config = AppConfig(**data)
            return _config

    _config = AppConfig()
    return _config


def get_config() -> AppConfig:
    """Get the current config, loading defaults if needed."""
    if _config is None:
        return load_config()
    return _config


def reset_config() -> None:
    """Reset config (for testing)."""
    global _config
    _config = None
