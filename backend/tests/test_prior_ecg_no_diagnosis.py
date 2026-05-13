"""No-diagnosis contract guard for ``prior_ecg_service``.

The prior-ECG pillar must never auto-interpret an ECG. This test pins
that contract by grep-ing the service source file for forbidden
substrings. If a future change introduces any of these, the test
fails and forces a contract conversation.
"""

from __future__ import annotations

from pathlib import Path

import epcr_app.services.prior_ecg_service as prior_ecg_service


FORBIDDEN_SUBSTRINGS = ("STEMI", "arrhythmia", "interpretation", "detect")


def test_service_source_has_no_diagnostic_substrings() -> None:
    source_path = Path(prior_ecg_service.__file__)
    text = source_path.read_text(encoding="utf-8")
    # Case-insensitive substring check so "Detect", "DETECT", and
    # "detection" are all caught.
    lower = text.lower()
    offenders: list[str] = []
    for token in FORBIDDEN_SUBSTRINGS:
        if token.lower() in lower:
            offenders.append(token)
    assert not offenders, (
        "prior_ecg_service.py must not contain diagnostic / "
        f"auto-interpretation substrings, found: {offenders}"
    )
