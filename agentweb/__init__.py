"""AgentWeb: high-quality web access CLI for agents."""

__version__ = "0.1.0"

from .api import AgentWebAPI
from .mechanics import AgentDefinition, ExecutionPolicy, ToolRegistry, ToolSpec
from .storage import AgentWebStore

__all__ = ["__version__", "AgentDefinition", "ExecutionPolicy", "ToolRegistry", "ToolSpec", "AgentWebStore", "AgentWebAPI"]
