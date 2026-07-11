"""Segment line items from filing XBRL instances (dimensional facts).

The companyfacts API returns only undimensioned totals, so segment splits —
MELI's Brazil/Mexico/Argentina revenue, a Commerce vs Fintech split, classic
reportable segments — never appear there. This module reads the **extracted
XBRL instances** (…_htm.xml) of up to ``SEGMENT_HISTORY_YEARS`` fiscal
years of 10-Ks plus the latest 10-Q, where those facts live as contexts
dimensioned by:

- ``us-gaap:StatementBusinessSegmentsAxis`` (reportable segments),
- ``srt:SubsegmentsAxis``                 (revenue streams, FIX-13b —
  MELI's Commerce/Fintech split),
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

**Merge order is the policy (FIX-10):** instances arrive oldest→newest
with the 10-Q LAST, so a plain later-wins per exact span equals
latest-restated — the 10-Q's comparatives are the freshest view of every
period they cover. The merge refuses to hide history: value revisions
land in ``recast_log``, membership changes at a shared fiscal year land
in ``breaks`` (a recast is never auto-spliced into one continuous-looking
series), and a renamed member merges only through the analyst-declared
alias map in the house file. Parsing is pure; fetching lives in
``edgar``.
"""
from __future__ import annotations

import datetime as dt
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import config
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
    # an interior fiscal year is missing while axis peers have it —
    # usually the shadow of a recast the filer did not restate backward
    discontinuous: bool = False

    def latest(self) -> Optional[float]:
        annual = [v for s, e, v in self.entries if 330 <= (e - s).days <= 400]
        return annual[-1] if annual else None


@dataclass
class SegmentData:
    lines: List[SegmentLine] = field(default_factory=list)
    source: str = ""
    status: str = ""  # human-readable diagnosis (footnoted when empty)
    recast_log: List[str] = field(default_factory=list)   # value overrides
    breaks: List[str] = field(default_factory=list)       # membership changes
    coverage: List[Tuple[str, int]] = field(default_factory=list)
    #                                 (instance label, matched fact count)

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


def _is_fy_span(span: Span) -> bool:
    return 330 <= (span[1] - span[0]).days <= 400


# FIX-14d: a tie row (and the Phase-2 gate) needs a real disclosure to
# referee — a deliberately partial axis (one member covering a sliver of
# revenue, e.g. a US-only geography note) only wolf-cries a huge red gap
# and trains the eye to ignore the rows that matter.
MIN_TIE_MEMBERS = 2
MIN_TIE_COVERAGE = 0.50


def partial_axis_disclosure(n_members: int, sigma: Optional[float],
                            total: Optional[float]) -> bool:
    """True when an axis' disclosure is too partial to tie out: fewer than
    MIN_TIE_MEMBERS members carry values at the gate span AND Σ covers less
    than MIN_TIE_COVERAGE of consolidated there (an unknown consolidated
    total counts as uncovered)."""
    if n_members >= MIN_TIE_MEMBERS:
        return False
    if (sigma is not None and total is not None and total > 0
            and sigma >= MIN_TIE_COVERAGE * total):
        return False
    return True


def _alias_parsed(parsed: ParsedInstance,
                  aliases: Dict[str, str]) -> ParsedInstance:
    """Rewrite member labels through the analyst alias map, pre-merge.

    Aliases are analyst-declared identity (old label → canonical label);
    applying them before keying makes a renamed member merge naturally
    under later-wins. No fuzzy matching anywhere — an alias exists only
    if the analyst wrote it in the house file.
    """
    if not aliases:
        return parsed
    out = ParsedInstance()
    # the FIX-13 bookkeeping rides along; qname accounting follows the
    # canonical (post-alias) label so merges stay attributed correctly
    out.n_multi = parsed.n_multi
    out.conflicts = list(parsed.conflicts)
    for (axis, member), qns in parsed.member_qnames.items():
        mkey = (axis, aliases.get(member, member))
        out.member_qnames.setdefault(mkey, set()).update(qns)

    def _collapse(bucket, key, spans, shown):
        """An alias collapsing two SAME-instance members must not become a
        silent third override path: keep the first value per span; a > 1%
        disagreement warns (mirrors the FIX-13c qname guard) — the alias
        map probably folds members that are not actually one entity."""
        tgt = bucket.setdefault(key, {})
        for span, val in spans.items():
            old = tgt.get(span)
            if old is None:
                tgt[span] = val
            elif abs(old - val) > 0.01 * max(abs(old), abs(val), 1e-9):
                out.conflicts.append(
                    f"alias collapse disagreement for {shown} on "
                    f"{span[1].isoformat()} ({old:,.0f} vs {val:,.0f}) — "
                    "kept the first; check the [segment_aliases] map")

    for (axis, member, concept), spans in parsed.singles.items():
        canon = aliases.get(member, member)
        _collapse(out.singles, (axis, canon, concept), spans, canon)
    for (ax1, m1, ax2, m2, concept), spans in parsed.crosses.items():
        c1, c2 = aliases.get(m1, m1), aliases.get(m2, m2)
        _collapse(out.crosses, (ax1, c1, ax2, c2, concept), spans,
                  f"{c1} × {c2}")
    return out


def _default_source(labels: List[str]) -> str:
    """'10-K …(FY2016)…(FY2025)… + 10-Q q26' → '10-K FY2016–FY2025 + 10-Q …'."""
    years = sorted({int(m.group(1)) for lbl in labels
                    for m in [re.search(r"\(FY(\d{4})\)", lbl)] if m})
    bits = []
    if years:
        bits.append(f"10-K FY{years[0]}–FY{years[-1]}" if len(years) > 1
                    else f"10-K FY{years[0]}")
    tenq = next((lbl for lbl in labels if lbl.startswith("10-Q")), None)
    if tenq:
        bits.append(tenq)
    return " + ".join(bits) or ", ".join(labels)


def build_segment_data(instances: List[Tuple[str, str]],  # (label, xml)
                       source: str = "",
                       aliases: Optional[Dict[str, str]] = None,
                       skipped: Optional[List[str]] = None) -> SegmentData:
    """Merge parsed instances into ordered segment lines, with provenance.

    Instances arrive oldest→newest with the 10-Q last, so a plain
    later-wins per exact span equals latest-restated. The merge refuses to
    hide history: value overrides beyond 1% land in ``recast_log`` (with
    both instance labels), membership changes at a shared fiscal year land
    in ``breaks`` (a recast boundary is NEVER auto-spliced — a renamed
    member stays two lines unless the analyst declares the identity in the
    alias map), per-instance match counts land in ``coverage``, and a
    member missing an interior year its peers have is flagged
    discontinuous. Single-axis totals missing from the filings are
    synthesized by summing the two-axis disaggregation across the crossing
    axis; within each (axis, member, group) the concept with the most
    observations represents the group; members order by latest revenue.
    """
    aliases = aliases or {}
    result_skipped: List[str] = list(skipped or [])
    singles: Dict[Tuple[str, str, str], Dict[Span, float]] = {}
    crosses: Dict[Tuple[str, str, str, str, str], Dict[Span, float]] = {}
    n_multi = 0                                        # FIX-13b accounting
    member_qnames: Dict[Tuple[str, str], set] = {}     # FIX-13c accounting
    conflicts: List[str] = []
    origin: Dict[Tuple, Dict[Span, str]] = {}  # merged key -> span -> label
    coverage: List[Tuple[str, int]] = []
    recast_log: List[str] = []
    breaks: List[str] = []
    # per-annual-instance membership index for break detection:
    # [(label, {axis: {FY span: set(members)}})], discarded after use
    membership: List[Tuple[str, Dict[str, Dict[Span, set]]]] = []

    def merge(target, key, spans, label, describe):
        tgt = target.setdefault(key, {})
        org = origin.setdefault(key, {})
        for span, val in spans.items():
            old = tgt.get(span)
            if old is not None and abs(val - old) > max(0.01 * abs(old), 1.0):
                recast_log.append(
                    f"{describe} {span[0].isoformat()}–{span[1].isoformat()}: "
                    f"{old:,.0f} → {val:,.0f} "
                    f"({org.get(span, '?')} → {label})")
            tgt[span] = val
            org[span] = label

    for label, xml_text in instances:
        try:
            parsed = parse_instance(xml_text)
        except ET.ParseError:
            result_skipped.append(f"{label}: parse error")
            continue
        parsed = _alias_parsed(parsed, aliases)
        n_multi += parsed.n_multi
        for mkey, qns in parsed.member_qnames.items():
            member_qnames.setdefault(mkey, set()).update(qns)
        for warn in parsed.conflicts:
            if warn not in conflicts:
                conflicts.append(warn)
        n_facts = (sum(len(s) for s in parsed.singles.values())
                   + sum(len(s) for s in parsed.crosses.values()))
        coverage.append((label, n_facts))
        if not label.startswith("10-Q"):
            idx: Dict[str, Dict[Span, set]] = {}
            for (axis, member, _c), spans in parsed.singles.items():
                for span in spans:
                    if _is_fy_span(span):
                        idx.setdefault(axis, {}).setdefault(span,
                                                            set()).add(member)
            for (ax1, m1, ax2, m2, _c), spans in parsed.crosses.items():
                for span in spans:
                    if _is_fy_span(span):
                        idx.setdefault(ax1, {}).setdefault(span,
                                                           set()).add(m1)
                        idx.setdefault(ax2, {}).setdefault(span,
                                                           set()).add(m2)
            membership.append((label, idx))
        for key, spans in parsed.singles.items():
            axis, member, concept = key
            merge(singles, key, spans, label, f"{axis}/{member} {concept}")
        for key, spans in parsed.crosses.items():
            ax1, m1, ax2, m2, concept = key
            merge(crosses, key, spans, label,
                  f"{ax1}/{m1} × {ax2}/{m2} {concept}")

    # membership breaks: adjacent annual filings, shared FY spans per axis
    for (label_i, idx_i), (label_j, idx_j) in zip(membership, membership[1:]):
        for axis in sorted(set(idx_i) & set(idx_j)):
            for span in sorted(set(idx_i[axis]) & set(idx_j[axis])):
                retired = idx_i[axis][span] - idx_j[axis][span]
                introduced = idx_j[axis][span] - idx_i[axis][span]
                if retired or introduced:
                    breaks.append(
                        f"{axis} @ FY{span[1].year}: "
                        f"retired {sorted(retired)}, "
                        f"introduced {sorted(introduced)} "
                        f"({label_i} → {label_j})")

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

    # discontinuity: an interior FY hole while (axis, group) peers have it
    def fy_years(ln: SegmentLine) -> set:
        return {e.year for s, e, _ in ln.entries if _is_fy_span((s, e))}

    for ln in lines:
        mine = fy_years(ln)
        if len(mine) < 2:
            continue
        peers = set().union(*(fy_years(o) for o in lines
                              if o is not ln and o.axis == ln.axis
                              and o.group == ln.group), set())
        ln.discontinuous = any(y not in mine and y in peers
                               for y in range(min(mine) + 1, max(mine)))

    bits: List[str] = []
    if synthesized:
        bits.append(f"{synthesized} single-axis spans aggregated from the "
                    "two-axis disaggregation table")
    # FIX-13c: duplicate-qname merges declared per (axis, label)
    for (_axis, mlabel), qns in sorted(member_qnames.items()):
        if len(qns) >= 2:  # a merge actually collapsed distinct qnames
            bits.append(f"member aliases merged: {mlabel} "
                        f"({len(qns)} qnames)")
    bits.extend(conflicts)
    if n_multi:  # FIX-13b: honest 3+-axis boundary
        bits.append(f"{n_multi} facts at 3+ segment axes ignored "
                    "(beyond the 2-axis model)")
    if coverage:
        matched = sum(1 for _, n in coverage if n > 0)
        bits.append(f"dimensional facts in {matched}/{len(coverage)} "
                    "instances")
    if recast_log:
        bits.append(f"{len(recast_log)} restated segment value(s) "
                    "across filings")
    if breaks:
        bits.append(f"{len(breaks)} membership break(s)")
    if result_skipped:
        bits.append("skipped: " + "; ".join(result_skipped))
    if not source:
        source = _default_source([lbl for lbl, _ in instances])
    return SegmentData(lines=lines, source=source, status="; ".join(bits),
                       recast_log=recast_log, breaks=breaks,
                       coverage=coverage)


def undimensioned_annual_facts(
        xml_text: str, local_names) -> Dict[Span, float]:
    """Consolidated (dimension-free) full-year USD facts whose element
    LOCAL NAME is in `local_names` — namespace-agnostic, so a company
    extension element (e.g. meli:InterestExpenseAndOtherFinancialCharges)
    matches by the same name as its us-gaap candidate. The companyfacts
    API serves standard taxonomies only, so an extension-tagged income-
    statement line exists nowhere BUT the filing instance."""
    root = ET.fromstring(xml_text)
    usd_units = set()
    for unit in root.iter():
        if _local(unit.tag) != "unit":
            continue
        measures = [m.text or "" for m in unit.iter()
                    if _local(m.tag) == "measure"]
        if any(_local(m) == "USD" for m in measures):
            usd_units.add(unit.get("id", ""))
    spans: Dict[str, Span] = {}
    for ctx in root.iter():
        if _local(ctx.tag) != "context":
            continue
        start = end = None
        has_dims = False
        for el in ctx.iter():
            ln = _local(el.tag)
            if ln == "startDate":
                start = _parse_date(el.text)
            elif ln == "endDate":
                end = _parse_date(el.text)
            elif ln in ("explicitMember", "typedMember"):
                has_dims = True
        if has_dims or start is None or end is None:
            continue
        if not 330 <= (end - start).days <= 400:  # full fiscal years only
            continue
        spans[ctx.get("id", "")] = (start, end)
    wanted = set(local_names)
    out: Dict[Span, float] = {}
    for el in root.iter():
        if _local(el.tag) not in wanted:
            continue
        span = spans.get(el.get("contextRef", ""))
        if span is None or el.get("unitRef", "") not in usd_units:
            continue
        try:
            out[span] = float((el.text or "").strip())
        except ValueError:
            continue
    return out


def rescue_annual_series(annual: AnnualFundamentals, concept: str,
                         cache: Optional[Cache] = None) -> List[int]:
    """Fill None years of `annual.series[concept]` from the consolidated
    facts of the (already-cached) filing instances; later filings win per
    span (latest-restated). Returns the fiscal years filled. Rides the
    same fetch/UA gate as segments; any failure returns [] — enrichment
    only. Never overwrites a companyfacts value."""
    series = list(annual.series.get(concept) or
                  [None] * len(annual.fy_ends))
    if not annual.fy_ends or all(v is not None for v in series):
        return []
    try:
        instances, _skipped = fetch_segment_instances(annual, cache=cache)
    except Exception:
        return []
    if not instances:
        return []
    local_names = DURATION_TAGS.get(concept, [])
    by_span: Dict[Span, float] = {}
    for _label, xml in instances:  # oldest→newest: later filings overwrite
        try:
            by_span.update(undimensioned_annual_facts(xml, local_names))
        except ET.ParseError:
            continue
    filled: List[int] = []
    for i, fe in enumerate(annual.fy_ends):
        if i < len(series) and series[i] is not None:
            continue
        for (s, e), v in by_span.items():
            if abs((e - fe).days) <= 7:
                series[i] = v
                filled.append(fe.year)
                break
    if not filled:
        return []
    annual.series[concept] = series
    tag = annual.tags_used.get(concept, "")
    years = (f"FY{min(filled)}–FY{max(filled)}" if len(filled) > 1
             else f"FY{filled[0]}")
    note = f"{years} rescued from filing instances"
    annual.tags_used[concept] = (f"{tag} ({note})" if tag
                                 else f"instance rescue ({note})")
    annual.selection_notes.append(
        f"{concept}: {len(filled)} fiscal year(s) rescued from the filing "
        "instances' consolidated facts — the line is extension-tagged and "
        "the companyfacts API serves standard taxonomies only")
    return sorted(filled)


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
    aliases = config.SEGMENT_ALIASES.get((annual.ticker or "").upper(), {})
    data = build_segment_data(instances, aliases=aliases, skipped=skipped)
    # honest shortfall: fewer annual instances than the history window asks
    n_annual = sum(1 for lbl, _ in instances if not lbl.startswith("10-Q"))
    want = min(config.SEGMENT_HISTORY_YEARS,
               len(annual.fy_ends) or config.SEGMENT_HISTORY_YEARS)
    if annual.annual_filings and n_annual < want:
        data.status = ((data.status + "; ") if data.status else "") + \
            f"only {n_annual} annual instance(s) available (requested {want})"
    if not data.lines:
        data.status = ((f"{len(instances)} instance(s) fetched but no facts "
                        "matched the segment axes — please report this "
                        "filer so the axis map can be extended")
                       + (("; " + data.status) if data.status else ""))
    return data
