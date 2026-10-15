"""Log redaction."""

from nomadquant.logging import redact_text


def test_redact_replaces_configured_secrets_and_assignments() -> None:
    secret = "paper-secret-value"
    text = f"authorization: Bearer {secret} api_key=abc123"
    redacted = redact_text(text, [secret])
    assert secret not in redacted
    assert "abc123" not in redacted
    assert "[REDACTED]" in redacted
