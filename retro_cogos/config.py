"""YAML configuration loading with Pydantic validation."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import yaml
from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o"
    api_key: str = "sk-placeholder"
    max_tokens: int = 4096
    temperature: float = 0.7


class DatabaseConfig(BaseModel):
    path: str = "retro_cogos_data.db"


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
    output_dir: str = "output"


class AppConfig(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    tool_permissions: Dict[str, str] = Field(default_factory=lambda: {"default": "confirm"})
    reflection: ReflectionConfig = Field(default_factory=ReflectionConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)


_config: AppConfig | None = None


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """Load config from YAML file. Falls back to defaults if file not found."""
    global _config
    if _config is not None:
        return _config

    paths_to_try = []
    if config_path:
        paths_to_try.append(Path(config_path))
    paths_to_try.extend([Path("config.yaml"), Path("config.yml")])

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
