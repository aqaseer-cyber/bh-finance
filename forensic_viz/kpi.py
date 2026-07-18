"""v3 R3a (a3): the stale-series KPI guard.

A strip KPI whose underlying series dies before the latest fiscal year
must never present the relic value as current — the design's example is
"FCF ex-SBC $110.2M" surviving three years after the SBC tag went dark.
`stale_note` is the single generic check (tail-aligned last-index test
against the fiscal-year labels); overview.js mirrors it for the web KPI
strip and the R3b report strip consumes it directly.
"""
from __future__ import annotations

from typing import Optional, Sequence


def stale_note(series: Optional[Sequence],
               fy_labels: Sequence[str]) -> Optional[str]:
    """``"n/a (series ends FY20xx)"`` when the series' last observation
    predates the latest fiscal year; None when the KPI may show its value.

    `series` is tail-aligned with `fy_labels`: engine series are padded
    to the label window (equal length), and a shorter series aligns at
    the tail, matching the chart join. An all-None/empty series returns
    None — there is no year to cite, ordinary n/a formatting applies.
    """
    if not fy_labels:
        return None
    seq = list(series or [])
    last_idx = None
    for i in range(len(seq) - 1, -1, -1):
        if seq[i] is not None:
            last_idx = i
            break
    if last_idx is None:
        return None
    label_idx = last_idx + (len(fy_labels) - len(seq))
    if label_idx >= len(fy_labels) - 1:
        return None
    if label_idx < 0:
        return f"n/a (series ends before {fy_labels[0]})"
    return f"n/a (series ends {fy_labels[label_idx]})"
