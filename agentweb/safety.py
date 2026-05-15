"""Safety, input limits, and output classification for AgentWeb."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class GuardResult:
    ok: bool
    code: str
    message: str


@dataclass(frozen=True)
class SafetyDecision:
    domain: str
    action: str
    message: str


class InputGuard:
    """Validate user text and uploads before expensive or risky processing."""

    def __init__(self, *, max_text_chars: int = 12000, max_upload_bytes: int = 10_000_000, allowed_extensions: set[str] | None = None) -> None:
        self.max_text_chars = max_text_chars
        self.max_upload_bytes = max_upload_bytes
        self.allowed_extensions = allowed_extensions or {".pdf", ".txt", ".md", ".html", ".csv", ".json", ".docx"}

    def validate_text(self, text: str) -> GuardResult:
        if not text or not text.strip():
            return GuardResult(False, "empty_input", "Enter some text before running this workflow.")
        if "\x00" in text:
            return GuardResult(False, "null_bytes", "Input contains null bytes.")
        if len(text) > self.max_text_chars:
            return GuardResult(False, "input_too_large", f"Input is too large; limit is {self.max_text_chars} characters.")
        return GuardResult(True, "ok", "ok")

    def validate_upload(self, *, filename: str, size_bytes: int) -> GuardResult:
        suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if suffix not in self.allowed_extensions:
            return GuardResult(False, "unsupported_file_type", f"Unsupported file type {suffix or '<none>'}.")
        if size_bytes > self.max_upload_bytes:
            return GuardResult(False, "upload_too_large", f"Upload is too large; limit is {self.max_upload_bytes} bytes.")
        return GuardResult(True, "ok", "ok")


class SafetyPolicy:
    """Subject-matter safety policy for high-risk domains."""

    high_risk = {
        "medical": ("insulin", "dose", "diagnose", "symptom", "therapy", "prescription", "clinical"),
        "legal": ("lawsuit", "contract", "liability", "legal advice", "court", "statute"),
        "financial": ("invest", "portfolio", "tax", "loan", "bankruptcy", "securities"),
        "security": ("exfiltrate", "steal", "credential", "malware", "phishing", "exploit"),
        "emergency": ("suicide", "overdose", "chest pain", "emergency", "bleeding"),
    }

    refusal_markers = ("exfiltrate", "steal", "malware", "phishing", "credential", "api keys")

    def evaluate(self, text: str) -> SafetyDecision:
        lower = text.lower()
        domain = "general"
        for candidate, markers in self.high_risk.items():
            if any(marker in lower for marker in markers):
                domain = candidate
                break
        if any(marker in lower for marker in self.refusal_markers):
            return SafetyDecision(domain=domain, action="refuse", message="I can’t help with credential theft, exfiltration, malware, or abuse.")
        if domain in {"medical", "legal", "financial", "emergency"}:
            return SafetyDecision(domain=domain, action="defer_with_disclaimer", message=f"This is {domain} information, not professional advice. Use qualified help for decisions.")
        return SafetyDecision(domain=domain, action="allow", message="ok")


_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{10,}"),
    re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]{10,}", re.IGNORECASE),
    re.compile(r"((?:api[_-]?key|token|secret|password)\s*[=:]\s*)[^\s&]+", re.IGNORECASE),
]


def redact_secrets(text: str) -> str:
    redacted = text
    redacted = _SECRET_PATTERNS[0].sub("[REDACTED]", redacted)
    redacted = _SECRET_PATTERNS[1].sub(r"\1[REDACTED]", redacted)
    redacted = _SECRET_PATTERNS[2].sub(r"\1[REDACTED]", redacted)
    return redacted


def classify_output_claims(text: str) -> dict[str, str]:
    lower = text.lower()
    if any(marker in lower for marker in ("in my opinion", "i think", "prefer", "cleaner", "better")):
        return {"claim_type": "opinion"}
    if any(marker in lower for marker in ("speculate", "could", "might happen", "forecast")):
        return {"claim_type": "speculative"}
    if any(marker in lower for marker in ("might", "uncertain", "limited", "unknown", "not clear")):
        return {"claim_type": "uncertain"}
    if any(marker in lower for marker in ("according to", "source", "citation", "study", "evidence")):
        return {"claim_type": "factual"}
    return {"claim_type": "factual" if text.strip() else "uncertain"}
