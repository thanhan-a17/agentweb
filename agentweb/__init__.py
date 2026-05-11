"""AgentWeb: high-quality web access CLI for agents."""

from .mechanics import AgentDefinition, ExecutionPolicy, ToolRegistry, ToolSpec
from .storage import AgentWebStore

__all__ = ["__version__", "AgentDefinition", "ExecutionPolicy", "ToolRegistry", "ToolSpec", "AgentWebStore"]
__version__ = "0.1.0"
