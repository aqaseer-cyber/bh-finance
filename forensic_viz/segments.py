"""Segment line items from filing XBRL instances (dimensional facts).

The companyfacts API returns only undimensioned totals, so segment splits —
MELI's Brazil/Mexico/Argentina revenue, a Commerce vs Fintech split, classic
reportable segments — never appear there. This module reads the **extracted
XBRL instance** (…_htm.xml) of the latest 10-K and 10-Q, where those facts
live as contexts dimensioned by:

- ``us-gaap:StatementBusinessSegmentsAxis`` (reportable segments),
- ``srt:ProductOrServiceAxis``            (revenue disaggregation),
- ``srt:StatementGeographicalAxis``       (geographic split).

Only revenue-family and operating-income concepts are collected, in USD.
History depth equals what those two filings carry (a 10-K brings 2–3
comparative years; the 10-Q brings the current quarters + year-ago
comparatives) — enough for the SOTP revenue architecture without crawling
the whole archive. Parsing is pure; fetching lives in ``edgar``.
"""
from __future__ import annotations

import datetime as dt
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .cache import Cache
from .edgar import (
    DURATION_TAGS, AnnualFundamentals, fetch_segment_instances,
)

_AXES = {  # local name -> display label
    "StatementBusinessSegmentsAxis": "business segments",
    "ProductOrServiceAxis": "product / service",
    "StatementGeographicalAxis": "geography",
}
_AXIS_ORDER = ["StatementBusinessSegmentsAxis", "ProductOrServiceAxis",
               "StatementGeographicalAxis"]
# extra dimensions that may accompany a segment axis without changing it
_NEUTRAL = {("ConsolidationItemsAxis", "OperatingSegmentsMember")}

_CONCEPT_GROUPS = {  # instance concept local name -> display group
    **{t: "Revenue" for t in DURATION_TAGS["revenue"]},
    "OperatingIncomeLoss": "Operating income",
    "GrossProfit": "Gross profit",
}

Entry = Tuple[dt.date, dt.date, float]


@dataclass
class SegmentLine:
    axis: str            # display label, e.g. "geography"
    member: str          # display label, e.g. "Brazil"
    group: str           # "Revenue" / "Operating income" / "Gross profit"
    entries: List[Entry] = field(default_factory=list)

    def latest(self) -> Optional[float]:
        annual = [v for s, e, v in self.entries if 330 <= (e - s).days <= 400]
        return annual[-1] if annual else None


@dataclass
class SegmentData:
    lines: List[SegmentLine] = field(default_factory=list)
    source: str = ""

    def axes(self) -> List[str]:
        seen: List[str] = []
        for ln in self.lines:
            if ln.axis not in seen:
                seen.append(ln.axis)
        return seen

    def members(self, axis: str) -> List[str]:
        seen: List[str] = []
        for ln in self.lines:
            if ln.axis == axis and ln.member not in seen:
                seen.append(ln.member)
        return seen

    @property
    def n_segments(self) -> int:
        """Members on the primary (first populated) axis."""
        ax = self.axes()
        return len(self.members(ax[0])) if ax else 0


def _local(tag_or_qname: str) -> str:
    """Local name of '{ns}tag' or 'prefix:tag'."""
    s = tag_or_qname.strip()
    if s.startswith("{"):
        return s.rsplit("}", 1)[1]
    return s.rsplit(":", 1)[-1]


def member_label(qname: str) -> str:
    """'meli:FintechServicesMember' -> 'Fintech Services'."""
    name = _local(qname)
    name = re.sub(r"Member$", "", name)
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])",
                  " ", name)
    return name.strip() or qname


def _parse_date(s: Optional[str]) -> Optional[dt.date]:
    try:
        return dt.date.fromisoformat((s or "").strip())
    except ValueError:
        return None


def parse_instance(xml_text: str) -> Dict[Tuple[str, str, str], List[Entry]]:
    """(axis local, member label, concept local) -> duration entries.

    Accepts only duration contexts carrying exactly one segment axis
    (plus the neutral OperatingSegments consolidation marker) and only
    USD facts for the whitelisted concepts.
    """
    root = ET.fromstring(xml_text)

    usd_units = set()
    for unit in root.iter():
        if _local(unit.tag) != "unit":
            continue
        measures = [m.text or "" for m in unit.iter()
                    if _local(m.tag) == "measure"]
        if any(_local(m) == "USD" for m in measures):
            usd_units.add(unit.get("id", ""))

    contexts: Dict[str, Tuple[str, str, dt.date, dt.date]] = {}
    for ctx in root.iter():
        if _local(ctx.tag) != "context":
            continue
        start = end = None
        dims: List[Tuple[str, str]] = []
        for el in ctx.iter():
            ln = _local(el.tag)
            if ln == "startDate":
                start = _parse_date(el.text)
            elif ln == "endDate":
                end = _parse_date(el.text)
            elif ln == "explicitMember":
                dims.append((_local(el.get("dimension", "")),
                             (el.text or "").strip()))
        if start is None or end is None or not dims:
            continue
        if not 20 <= (end - start).days <= 400:
            continue
        seg_dims = [(a, m) for a, m in dims
                    if (a, _local(m)) not in _NEUTRAL]
        if len(seg_dims) != 1 or seg_dims[0][0] not in _AXES:
            continue  # multi-dimension or non-segment context
        axis, member = seg_dims[0]
        contexts[ctx.get("id", "")] = (axis, member_label(member), start, end)

    out: Dict[Tuple[str, str, str], Dict[Tuple[dt.date, dt.date], float]] = {}
    for el in root.iter():
        concept = _local(el.tag)
        if concept not in _CONCEPT_GROUPS:
            continue
        ctx = contexts.get(el.get("contextRef", ""))
        if ctx is None or el.get("unitRef", "") not in usd_units:
            continue
        try:
            val = float((el.text or "").strip())
        except ValueError:
            continue
        axis, member, start, end = ctx
        out.setdefault((axis, member, concept), {})[(start, end)] = val
    return {k: [(s, e, v) for (s, e), v in sorted(spans.items())]
            for k, spans in out.items()}


def build_segment_data(instances: List[str], source: str = "") -> SegmentData:
    """Merge parsed instances into ordered segment lines.

    Later instances win on identical spans. Within each (axis, member),
    the revenue-family concept with the most observations represents the
    "Revenue" group. Members are ordered by latest annual revenue.
    """
    merged: Dict[Tuple[str, str, str], Dict[Tuple[dt.date, dt.date], float]] = {}
    for xml_text in instances:
        try:
            parsed = parse_instance(xml_text)
        except ET.ParseError:
            continue
        for key, entries in parsed.items():
            merged.setdefault(key, {}).update(
                {(s, e): v for s, e, v in entries})

    # pick one concept per (axis, member, group): most observations wins
    best: Dict[Tuple[str, str, str], Tuple[int, str]] = {}
    for (axis, member, concept), spans in merged.items():
        group = _CONCEPT_GROUPS[concept]
        key = (axis, member, group)
        cand = (len(spans), concept)
        if key not in best or cand > best[key]:
            best[key] = cand

    lines: List[SegmentLine] = []
    for (axis, member, group), (_, concept) in best.items():
        spans = merged[(axis, member, concept)]
        lines.append(SegmentLine(
            axis=_AXES[axis], member=member, group=group,
            entries=[(s, e, v) for (s, e), v in sorted(spans.items())]))

    axis_rank = {_AXES[a]: i for i, a in enumerate(_AXIS_ORDER)}
    group_rank = {"Revenue": 0, "Operating income": 1, "Gross profit": 2}
    rev_size = {(ln.axis, ln.member): -(ln.latest() or 0.0)
                for ln in lines if ln.group == "Revenue"}
    lines.sort(key=lambda ln: (axis_rank.get(ln.axis, 9),
                               group_rank.get(ln.group, 9),
                               rev_size.get((ln.axis, ln.member), 0.0),
                               ln.member))
    return SegmentData(lines=lines, source=source)


def fetch_segment_data(annual: AnnualFundamentals,
                       cache: Optional[Cache] = None) -> Optional[SegmentData]:
    """Fetch + parse the latest 10-K/10-Q instances; None when unavailable."""
    instances = fetch_segment_instances(annual, cache=cache)
    if not instances:
        return None
    bits = []
    if annual.latest_10k_accession:
        bits.append(f"10-K {annual.latest_10k_accession}")
    if annual.latest_10q_accession:
        bits.append(f"10-Q {annual.latest_10q_accession}")
    data = build_segment_data(instances, source=", ".join(bits))
    return data if data.lines else None
