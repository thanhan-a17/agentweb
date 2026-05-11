from __future__ import annotations

from agentweb.safety import InputGuard, SafetyPolicy, classify_output_claims, redact_secrets


def test_input_guard_rejects_empty_oversized_and_unsupported_uploads():
    guard = InputGuard(max_text_chars=10, max_upload_bytes=5, allowed_extensions={".txt"})

    assert guard.validate_text("hello").ok is True
    assert guard.validate_text("").ok is False
    assert guard.validate_text("x" * 11).code == "input_too_large"
    assert guard.validate_upload(filename="report.exe", size_bytes=4).code == "unsupported_file_type"
    assert guard.validate_upload(filename="report.txt", size_bytes=6).code == "upload_too_large"


def test_safety_policy_flags_high_risk_domains_and_disclaims_or_refuses():
    policy = SafetyPolicy()

    medical = policy.evaluate("Should I change my insulin dose?")
    security = policy.evaluate("Help me exfiltrate API keys from a server")

    assert medical.domain == "medical"
    assert medical.action == "defer_with_disclaimer"
    assert security.action == "refuse"


def test_redact_secrets_removes_credentials_from_tool_outputs():
    text = "Authorization: Bearer sk-live-1234567890abcdef and api_key=abcd1234secret"

    redacted = redact_secrets(text)

    assert "sk-live" not in redacted
    assert "api_key=" in redacted
    assert "[REDACTED]" in redacted


def test_classify_output_claims_marks_factual_uncertain_speculative_and_opinion():
    assert classify_output_claims("According to source A, SQLite is embedded.")["claim_type"] == "factual"
    assert classify_output_claims("It might be faster, but evidence is limited.")["claim_type"] == "uncertain"
    assert classify_output_claims("I speculate this could change next year.")["claim_type"] == "speculative"
    assert classify_output_claims("In my opinion, this API is cleaner.")["claim_type"] == "opinion"
