from __future__ import annotations

from pathlib import Path


SOURCE = Path("src/metascan/pipeline/command_pipeline.py").read_text(encoding="utf-8")


def test_uncertainty_emits_reconciliation_without_resend() -> None:
    unknown = SOURCE.index('"EXECUTION_UNKNOWN", reason=reason, event_type="command.execution_unknown"')
    issue = SOURCE.index('"reconciliation.issue.detected"')
    assert unknown < issue
    assert "order_send" not in SOURCE
