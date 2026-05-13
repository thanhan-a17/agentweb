"""Scoped memory and retrieval primitives for AgentWeb."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .mechanics import PermissionDenied, ValidationError
from .storage import AgentWebStore


@dataclass(frozen=True)
class Scope:
    user: str = ""
    workspace: str = ""
    project: str = ""
    agent: str = ""
    task: str = ""

    def key(self) -> str:
        return "|".join([self.user, self.workspace, self.project, self.agent, self.task])

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class MemoryEntry:
    id: str
    title: str
    text: str
    source: str
    scope: Scope
    kind: str = "long_term"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["scope"] = self.scope.to_dict()
        return data


class RetrievalIndex:
    """Tiny in-memory lexical index with prompt-injection filtering and citations."""

    injection_markers = (
        "ignore previous instructions",
        "reveal secrets",
        "system prompt",
        "hidden instructions",
        "exfiltrate",
    )

    def __init__(self) -> None:
        self._entries: list[MemoryEntry] = []

    def add(self, entry: MemoryEntry) -> None:
        if self._is_injection(entry.text):
            return
        self._entries.append(entry)

    def search(self, query: str, *, scope: Scope, limit: int = 5) -> list[dict[str, Any]]:
        terms = _terms(query)
        scored: list[tuple[int, MemoryEntry]] = []
        for entry in self._entries:
            if entry.scope != scope:
                continue
            haystack = f"{entry.title} {entry.text}".lower()
            score = sum(1 for term in terms if term in haystack)
            if score:
                scored.append((score, entry))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            {
                "id": entry.id,
                "title": entry.title,
                "text": entry.text,
                "citation": entry.source,
                "source": entry.source,
                "scope": entry.scope.to_dict(),
                "score": score,
            }
            for score, entry in scored[:limit]
        ]

    def _is_injection(self, text: str) -> bool:
        lower = text.lower()
        return any(marker in lower for marker in self.injection_markers)


class MemoryStore:
    """SQLite-backed memory layer with explicit scope isolation."""

    def __init__(self, store: AgentWebStore, *, max_entry_chars: int = 12000) -> None:
        self.store = store
        self.max_entry_chars = max_entry_chars
        self.store.initialize()

    def set_enabled(self, *, scope: Scope, enabled: bool, actor: str = "system", request_id: str = "") -> None:
        with self.store.connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_config(scope_key, enabled, scope_json)
                VALUES (?, ?, ?)
                ON CONFLICT(scope_key) DO UPDATE SET enabled=excluded.enabled, scope_json=excluded.scope_json, updated_at=CURRENT_TIMESTAMP
                """,
                (scope.key(), 1 if enabled else 0, self.store.dump(scope.to_dict())),
            )
            self.store.audit(conn, actor=actor, action="memory.config", target=scope.key(), result="enabled" if enabled else "disabled", request_id=request_id)

    def add(self, title: str, text: str, *, scope: Scope, kind: str = "long_term", source: str = "memory", actor: str = "system", request_id: str = "") -> MemoryEntry:
        self._validate_text(text)
        if not self._enabled(scope):
            raise PermissionDenied(f"Memory scope is disabled: {scope.key()}")
        with self.store.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO memory_entries(title, text, source, kind, scope_key, scope_json, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (title, text, source, kind, scope.key(), self.store.dump(scope.to_dict()), self.store.dump({})),
            )
            entry_id = str(cursor.lastrowid)
            self.store.audit(conn, actor=actor, action="memory.add", target=entry_id, result="ok", request_id=request_id, details={"scope": scope.key()})
        return MemoryEntry(id=entry_id, title=title, text=text, source=source, scope=scope, kind=kind)

    def search(self, query: str, *, scope: Scope, limit: int = 5) -> list[MemoryEntry]:
        if not self._enabled(scope):
            return []
        terms = _terms(query)
        with self.store.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM memory_entries WHERE scope_key = ? ORDER BY id DESC",
                (scope.key(),),
            ).fetchall()
            self.store.audit(conn, actor=scope.user or "system", action="memory.search", target=scope.key(), result="ok", request_id="", details={"query": query})
        matches: list[tuple[int, MemoryEntry]] = []
        for row in rows:
            haystack = f"{row['title']} {row['text']}".lower()
            score = sum(1 for term in terms if term in haystack)
            if score:
                matches.append((score, self._entry_from_row(row)))
        matches.sort(key=lambda item: item[0], reverse=True)
        return [entry for _, entry in matches[:limit]]

    def clear(self, *, scope: Scope, actor: str = "system", request_id: str = "") -> int:
        with self.store.connect() as conn:
            cursor = conn.execute("DELETE FROM memory_entries WHERE scope_key = ?", (scope.key(),))
            count = cursor.rowcount
            self.store.audit(conn, actor=actor, action="memory.clear", target=scope.key(), result="ok", request_id=request_id, details={"deleted": count})
        return int(count)

    def _enabled(self, scope: Scope) -> bool:
        with self.store.connect() as conn:
            row = conn.execute("SELECT enabled FROM memory_config WHERE scope_key = ?", (scope.key(),)).fetchone()
        return row is None or bool(row["enabled"])

    def _validate_text(self, text: str) -> None:
        if not text.strip():
            raise ValidationError("memory.text: required")
        if len(text) > self.max_entry_chars:
            raise ValidationError(f"memory.text: exceeds max_entry_chars {self.max_entry_chars}")

    def _entry_from_row(self, row: Any) -> MemoryEntry:
        scope_data = self.store.load(row["scope_json"])
        return MemoryEntry(
            id=str(row["id"]),
            title=row["title"],
            text=row["text"],
            source=row["source"],
            kind=row["kind"],
            scope=Scope(**scope_data),
            metadata=self.store.load(row["metadata_json"]),
        )


def _terms(query: str) -> list[str]:
    return [term for term in query.lower().replace("-", " ").split() if len(term) > 2]
