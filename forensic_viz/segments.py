"""Segment line items from filing XBRL instances (dimensional facts).

The companyfacts API returns only undimensioned totals, so segment splits —
MELI's Brazil/Mexico/Argentina revenue, a Commerce vs Fintech split, classic
reportable segments — never appear there. This module reads the **extracted
XBRL instance** (…_htm.xml) of the latest 10-K and 10-Q, where those facts
live as contexts dimensioned by:

- ``us-gaap:StatementBusinessSegmentsAxis`` (reportable segments),
- ``srt:ProductOrServiceAxis``            (revenue disaggregation; the
  pre-2020 ``ProductsAndServicesAxis`` alias is accepted too),
- ``srt:StatementGeographicalAxis``       (geographic split).

Concepts collected (USD only): the revenue family, operating income, gross
profit, and any concept whose name carries ``DirectContribution`` — the
segment measure MELI-style filers define as an extension.

Filers like MELI tag their disaggregation table on TWO axes at once
(geography × business). Such cross facts are kept, and single-axis totals
are synthesized by summing across the other axis wherever the filer did
not tag the single-axis total directly — recorded in the status string.

History depth equals what the two filings carry (a 10-K brings 2–3
comparative years; the 10-Q the current quarters + year-ago comparatives).
Parsing is pure; fetching lives in ``edgar``.
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

_AXES = {  # accepted axis local name -> display label
    "StatementBusinessSegmentsAxis": "business segments",
    # MELI's Commerce/Fintech split rides srt:SubsegmentsAxis (FIX-13b)
    "SubsegmentsAxis": "revenue stream",
    "ProductOrServiceAxis": "product / service",
    "ProductsAndServicesAxis": "product / service",  # pre-2020 srt name
    "StatementGeographicalAxis": "geography",
}
_AXIS_ORDER = ["business segments", "revenue stream", "product / service",
               "geography"]
# extra dimensions that may accompany a segment axis without changing it
_NEUTRAL = {("ConsolidationItemsAxis", "OperatingSegmentsMember")}

_CONCEPT_GROUPS = {  # instance concept local name -> display group
    **{t: "Revenue" for t in DURATION_TAGS["revenue"]},
    "OperatingIncomeLoss": "Operating income",
    "GrossProfit": "Gross profit",
}
_GROUP_RANK = {"Revenue": 0, "Operating income": 1, "Direct contribution": 2,
               "Gross profit": 3}

# srt geography members are often bare ISO codes (country:BR)
_COUNTRY = {
    "US": "United States", "BR": "Brazil", "MX": "Mexico", "AR": "Argentina",
    "CL": "Chile", "CO": "Colombia", "PE": "Peru", "UY": "Uruguay",
    "CA": "Canada", "GB": "United Kingdom", "DE": "Germany", "FR": "France",
    "JP": "Japan", "CN": "China", "IN": "India", "IE": "Ireland",
    "NL": "Netherlands", "KR": "South Korea", "TW": "Taiwan",
}

Span = Tuple[dt.date, dt.date]
Entry = Tuple[dt.date, dt.date, float]


def _concept_group(local: str) -> Optional[str]:
    g = _CONCEPT_GROUPS.get(local)
    if g:
        return g
    if "DirectContribution" in local:
        return "Direct contribution"
    return None


@dataclass
class SegmentLine:
    axis: str            # display label, e.g. "geography"
    member: str          # display label, e.g. "Brazil"
    group: str           # "Revenue" / "Operating income" / …
    entries: List[Entry] = field(default_factory=list)
    # spans whose value was summed from the two-axis table (not filed
    # directly) — rendered distinctly so a reader can tell them apart
    synth: set = field(default_factory=set)

    def latest(self) -> Optional[float]:
        annual = [v for s, e, v in self.entries if 330 <= (e - s).days <= 400]
        return annual[-1] if annual else None


@dataclass
class SegmentData:
    lines: List[SegmentLine] = field(default_factory=list)
    source: str = ""
    status: str = ""  # human-readable diagnosis (footnoted when empty)

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


@dataclass
class ParsedInstance:
    """Facts split by dimensionality: single segment axis vs two crossed."""

    singles: Dict[Tuple[str, str, str], Dict[Span, float]] = \
        field(default_factory=dict)   # (axis, member, concept)
    crosses: Dict[Tuple[str, str, str, str, str], Dict[Span, float]] = \
        field(default_factory=dict)   # (ax1, m1, ax2, m2, concept)
    # FIX-13b: facts whose context crosses 3+ ACCEPTED axes — real detail
    # beyond the 2-axis model, counted so the status can declare them
    n_multi: int = 0
    # FIX-13c: (axis, label) -> raw member qnames that mapped onto it (so
    # duplicate-qname merges can be declared), and same-instance conflicts
    # where two qnames disagreed on one span (first kept, never averaged)
    member_qnames: Dict[Tuple[str, str], set] = field(default_factory=dict)
    conflicts: List[str] = field(default_factory=list)


def _local(tag_or_qname: str) -> str:
    """Local name of '{ns}tag' or 'prefix:tag'."""
    s = tag_or_qname.strip()
    if s.startswith("{"):
        return s.rsplit("}", 1)[1]
    return s.rsplit(":", 1)[-1]


def member_label(qname: str) -> str:
    """'meli:FintechServicesMember' -> 'Fintech Services'; 'country:BR' ->
    'Brazil'; 'meli:BrazilSegmentMember' -> 'Brazil'.

    A trailing 'Segment' is stripped after the 'Member' suffix (FIX-13c).
    Assumption: within one axis of one filer, a bare ``X`` and an
    ``XSegment`` member denote the same economic member — verified on MELI,
    whose business-segments axis carries both OtherCountriesMember and
    OtherCountriesSegmentMember with identical values."""
    name = re.sub(r"Member$", "", _local(qname))
    name = re.sub(r"Segment$", "", name)
    if name.upper() in _COUNTRY and len(name) == 2:
        return _COUNTRY[name.upper()]
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])",
                  " ", name)
    return name.strip() or qname


def _parse_date(s: Optional[str]) -> Optional[dt.date]:
    try:
        return dt.date.fromisoformat((s or "").strip())
    except ValueError:
        return None


def parse_instance(xml_text: str) -> ParsedInstance:
    """Duration facts on one or two accepted segment axes, USD only."""
    root = ET.fromstring(xml_text)

    usd_units = set()
    for unit in root.iter():
        if _local(unit.tag) != "unit":
            continue
        measures = [m.text or "" for m in unit.iter()
                    if _local(m.tag) == "measure"]
        if any(_local(m) == "USD" for m in measures):
            usd_units.add(unit.get("id", ""))

    # context id -> (sorted axis/member pairs, start, end)
    contexts: Dict[str, Tuple[List[Tuple[str, str]], dt.date, dt.date]] = {}
    multi_ctx: set = set()  # contexts on 3+ accepted axes (FIX-13b)
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
        if not seg_dims or any(a not in _AXES for a, _ in seg_dims):
            continue  # no segment axis, or a foreign axis present
        if len(seg_dims) > 2:
            # all-accepted 3+-axis contexts: counted (FIX-13b), not modeled
            multi_ctx.add(ctx.get("id", ""))
            continue
        # normalization happens HERE, at the earliest keying point, so
        # duplicate member qnames merge naturally (FIX-13c); the raw qname
        # rides along for merge accounting and the conflict guard
        pairs = sorted((_AXES[a], member_label(m), m) for a, m in seg_dims)
        contexts[ctx.get("id", "")] = (pairs, start, end)

    out = ParsedInstance()
    span_src: Dict[tuple, Tuple[tuple, float]] = {}  # who wrote each span

    def _store(kind, bucket, key, span, val, qsig, shown):
        """Keep-first per span across qname aliases: agreeing aliases merge
        silently; a > 1% disagreement keeps the first and warns — never
        average (FIX-13c)."""
        prev = span_src.get((kind, key, span))
        if prev is not None and prev[0] != qsig:
            pv = prev[1]
            if abs(pv - val) > 0.01 * max(abs(pv), abs(val), 1e-9):
                out.conflicts.append(
                    f"qname aliases disagree for {shown} on "
                    f"{span[1].isoformat()} ({pv:,.0f} vs {val:,.0f}) — "
                    "kept the first")
            return
        bucket.setdefault(key, {})[span] = val
        span_src[(kind, key, span)] = (qsig, val)

    for el in root.iter():
        group_concept = _local(el.tag)
        if _concept_group(group_concept) is None:
            continue
        if el.get("contextRef", "") in multi_ctx \
                and el.get("unitRef", "") in usd_units:
            out.n_multi += 1
            continue
        ctx = contexts.get(el.get("contextRef", ""))
        if ctx is None or el.get("unitRef", "") not in usd_units:
            continue
        try:
            val = float((el.text or "").strip())
        except ValueError:
            continue
        pairs, start, end = ctx
        for axis, member, qn in pairs:
            out.member_qnames.setdefault((axis, member), set()).add(qn)
        if len(pairs) == 1:
            (axis, member, qn), = pairs
            _store("s", out.singles, (axis, member, group_concept),
                   (start, end), val, (qn,), member)
        else:
            (ax1, m1, q1), (ax2, m2, q2) = pairs
            _store("x", out.crosses, (ax1, m1, ax2, m2, group_concept),
                   (start, end), val, (q1, q2), f"{m1} × {m2}")
    return out


def build_segment_data(instances: List[str], source: str = "") -> SegmentData:
    """Merge parsed instances into ordered segment lines.

    Later instances win on identical spans. Single-axis totals missing
    from the filing are synthesized by summing the two-axis disaggregation
    across the crossing axis (complete per span in a disaggregation
    table). Within each (axis, member, group), the concept with the most
    observations represents the group; members order by latest revenue.
    """
    singles: Dict[Tuple[str, str, str], Dict[Span, float]] = {}
    crosses: Dict[Tuple[str, str, str, str, str], Dict[Span, float]] = {}
    n_multi = 0
    member_qnames: Dict[Tuple[str, str], set] = {}
    conflicts: List[str] = []
    for xml_text in instances:
        try:
            parsed = parse_instance(xml_text)
        except ET.ParseError:
            continue
        n_multi += parsed.n_multi
        for mkey, qns in parsed.member_qnames.items():
            member_qnames.setdefault(mkey, set()).update(qns)
        for warn in parsed.conflicts:
            if warn not in conflicts:
                conflicts.append(warn)
        for key, spans in parsed.singles.items():
            singles.setdefault(key, {}).update(spans)
        for key, spans in parsed.crosses.items():
            crosses.setdefault(key, {}).update(spans)

    # synthesize single-axis totals from the two-axis table where absent
    synthesized = 0
    synth: Dict[Tuple[str, str, str], Dict[Span, float]] = {}
    adopted: Dict[Tuple[str, str, str], set] = {}
    for (ax1, m1, ax2, m2, concept), spans in crosses.items():
        for side_axis, side_member in ((ax1, m1), (ax2, m2)):
            key = (side_axis, side_member, concept)
            for span, val in spans.items():
                if span in singles.get(key, {}):
                    continue
                bucket = synth.setdefault(key, {})
                bucket[span] = bucket.get(span, 0.0) + val
    for key, spans in synth.items():
        for span, val in spans.items():
            if span not in singles.get(key, {}):
                singles.setdefault(key, {})[span] = val
                adopted.setdefault(key, set()).add(span)
                synthesized += 1

    # pick one concept per (axis, member, group): most observations wins
    best: Dict[Tuple[str, str, str], Tuple[int, str]] = {}
    for (axis, member, concept), spans in singles.items():
        group = _concept_group(concept)
        key = (axis, member, group)
        cand = (len(spans), concept)
        if key not in best or cand > best[key]:
            best[key] = cand

    lines: List[SegmentLine] = []
    for (axis, member, group), (_, concept) in best.items():
        spans = singles[(axis, member, concept)]
        lines.append(SegmentLine(
            axis=axis, member=member, group=group,
            entries=[(s, e, v) for (s, e), v in sorted(spans.items())],
            synth=adopted.get((axis, member, concept), set())))

    axis_rank = {a: i for i, a in enumerate(_AXIS_ORDER)}
    rev_size = {(ln.axis, ln.member): -(ln.latest() or 0.0)
                for ln in lines if ln.group == "Revenue"}
    lines.sort(key=lambda ln: (axis_rank.get(ln.axis, 9),
                               _GROUP_RANK.get(ln.group, 9),
                               rev_size.get((ln.axis, ln.member), 0.0),
                               ln.member))
    notes: List[str] = []
    if synthesized:
        notes.append(f"{synthesized} single-axis spans aggregated from the "
                     "two-axis disaggregation table")
    for (_axis, label), qns in sorted(member_qnames.items()):
        if len(qns) >= 2:  # a merge actually collapsed distinct qnames
            notes.append(f"member aliases merged: {label} "
                         f"({len(qns)} qnames)")
    notes.extend(conflicts)
    if n_multi:
        notes.append(f"{n_multi} facts at 3+ segment axes ignored "
                     "(beyond the 2-axis model)")
    return SegmentData(lines=lines, source=source, status="; ".join(notes))


def fetch_segment_data(annual: AnnualFundamentals,
                       cache: Optional[Cache] = None) -> SegmentData:
    """Fetch + parse the latest 10-K/10-Q instances.

    Always returns a SegmentData; when ``lines`` is empty the ``status``
    says why (unreachable instances vs no matching dimensional facts) so
    the workbook footnote can report the actual cause.
    """
    instances, skipped = fetch_segment_instances(annual, cache=cache)
    if not instances:
        if skipped:
            return SegmentData(
                status="all instances skipped: " + "; ".join(skipped))
        return SegmentData(status=(
            "filing XBRL instances unreachable (offline, or an unexpected "
            "EDGAR layout for this filer)"))
    data = build_segment_data([xml for _, xml in instances],
                              source=", ".join(lbl for lbl, _ in instances))
    if not data.lines:
        data.status = (f"{len(instances)} instance(s) fetched but no facts "
                       "matched the segment axes — please report this "
                       "filer so the axis map can be extended")
    return data
