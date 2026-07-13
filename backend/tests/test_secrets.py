"""Secrets never appear in repr/str/model_dump."""

from __future__ import annotations

from metascan.config import Credentials


def test_credentials_hidden_from_repr_str_dump() -> None:
    # FAKE fixture — never a real account.
    creds = Credentials(
        mt5_login="999001",
        mt5_password="FAKE-TEST-PASSWORD-2-NOT-REAL",
        mt5_server="Exness-MT5Trial",
        api_token="bearer_token_xyz",
    )
    for text in (repr(creds), str(creds)):
        assert "FAKE-TEST-PASSWORD-2-NOT-REAL" not in text
        assert "bearer_token_xyz" not in text
        assert "999001" not in text  # login also credential-class

    dumped = creds.model_dump()
    assert dumped["mt5_password"] != "FAKE-TEST-PASSWORD-2-NOT-REAL"
    assert dumped["api_token"] != "bearer_token_xyz"
    assert "FAKE-TEST-PASSWORD-2-NOT-REAL" not in str(dumped)
    assert "bearer_token_xyz" not in str(dumped)
