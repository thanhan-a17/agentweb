"""AgentWeb: high-quality web access CLI for agents."""

__version__ = "0.1.0"

from .api import AgentWebAPI
from .ingest import FileIngestor, IngestedDocument
from .mechanics import AgentDefinition, ExecutionPolicy, ToolRegistry, ToolSpec
from .memory import MemoryEntry, MemoryStore, Scope
from .orchestration import Orchestrator, Plan, TaskStep
from .storage import AgentWebStore

__all__ = [
    "__version__",
    "AgentDefinition",
    "ExecutionPolicy",
    "ToolRegistry",
    "ToolSpec",
    "AgentWebStore",
    "AgentWebAPI",
    "FileIngestor",
    "IngestedDocument",
    "MemoryEntry",
    "MemoryStore",
    "Scope",
    "Orchestrator",
    "Plan",
    "TaskStep",
]
