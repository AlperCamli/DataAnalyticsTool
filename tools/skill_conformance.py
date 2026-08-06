"""Skill-output rule validators (CP-5 deliverable 7, layer (a) of D-78).

Pure checkers over artifacts the skills produce: enrich drafts and report
artifacts. They pin the rules cheaply and run in CI forever.

**What these are not.** Per ruling D-78, these validators are *not* the
AS-9/10/12 conformance evidence. They cannot fail when a skill misbehaves
— the artifacts they read are staged by the test, so the suite stays green
whether or not the enrich skill ever writes a purpose. They test the
checker. The conformance evidence is the behavioral scenarios run against
the fixture deployment, which observe what an agent actually did.

    A conformance item may only be reported green on evidence that could
    have failed if the behavior were absent.

Deliberately outside `generator/`: that package is the KB CI validation
library, vendored into the customer KB as a wheel, and any change to it
carries the D-46 rebuild-and-PR obligation. These rules govern *skill
output*, not KB validity, and have no business widening that surface.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class Finding:
    check: str  # "CP-E4" | "AS-9" | "AS-10"
    detail: str
    level: str = "error"


# --------------------------------------------------------------------------
# CP-E4 / AS-12 — purposes live in front-matter, bodies carry the rest


_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)

# Body sections whose entire content a one-line front-matter value would
# carry. "Purpose" is the clear case; "Column meanings" is scoped rather
# than banned, since enum decodings legitimately live there.
_RESTATING_HEADINGS = {"purpose", "purposes"}


def _body_sections(body: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    matches = list(_HEADING.finditer(body))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        sections[m.group(1).strip().lower()] = body[m.end() : end].strip()
    return sections


def check_purpose_frontmatter(
    fm: Mapping[str, Any],
    body: str,
    *,
    columns: Sequence[str] = (),
) -> list[Finding]:
    """CP-E4: one-liners in front-matter; no body section restating them.

    An empty body under complete front-matter is valid and must not be
    flagged — objects whose meaning genuinely is one line per column
    should produce exactly that, not padding written to fill a template.
    """
    findings: list[Finding] = []

    purpose = fm.get("purpose")
    if not purpose or not str(purpose).strip():
        findings.append(Finding("CP-E4", "front-matter carries no `purpose`"))
    elif "\n" in str(purpose):
        findings.append(Finding("CP-E4", "`purpose` must be a single line"))

    col_purposes = fm.get("column_purposes") or {}
    if columns and not col_purposes:
        findings.append(Finding("CP-E4", "front-matter carries no `column_purposes`"))
    for key, value in (col_purposes or {}).items():
        if "\n" in str(value):
            findings.append(Finding("CP-E4", f"`column_purposes.{key}` must be a single line"))

    sections = _body_sections(body)
    for heading in sections:
        if heading in _RESTATING_HEADINGS:
            findings.append(
                Finding(
                    "CP-E4",
                    f"body section {heading!r} restates front-matter `purpose` — "
                    "two sources for one claim drift, and both look authoritative",
                )
            )

    # A body that only repeats a one-liner verbatim is the subtler version
    # of the same defect.
    if purpose:
        for heading, content in sections.items():
            if content and content.strip() == str(purpose).strip():
                findings.append(
                    Finding("CP-E4", f"body section {heading!r} duplicates `purpose` verbatim")
                )

    return findings


# --------------------------------------------------------------------------
# AS-9 — gap, never guess


def check_gap_not_guessed(
    *,
    unanswerable: Sequence[str],
    gaps: Sequence[str],
    drafted_docs: Mapping[str, str],
    frontmatter: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[Finding]:
    """Every unanswerable item is a named gap and appears as prose nowhere.

    `unanswerable` are the staged items the evidence cannot settle. Each
    must show up in `gaps`, and none may be asserted in a doc body or
    smuggled into a `column_purposes` one-liner — the front-matter route
    matters because that is the value the generator merges into machine
    docs, where it reads as fact.
    """
    findings: list[Finding] = []
    gap_text = " ".join(gaps).lower()

    for item in unanswerable:
        if item.lower() not in gap_text:
            findings.append(Finding("AS-9", f"unanswerable item {item!r} is not recorded as a gap"))

        for path, body in drafted_docs.items():
            # A mention inside an explicit gap/warning section is the
            # correct behavior, not a violation.
            sections = _body_sections(body)
            for heading, content in sections.items():
                if item.lower() in content.lower() and not _is_gap_heading(heading):
                    findings.append(
                        Finding(
                            "AS-9",
                            f"{path}: unanswerable item {item!r} asserted in section {heading!r} "
                            "rather than recorded as a gap",
                        )
                    )

        for path, fm in (frontmatter or {}).items():
            for key, value in (fm.get("column_purposes") or {}).items():
                if item.lower() in str(value).lower():
                    findings.append(
                        Finding(
                            "AS-9",
                            f"{path}: unanswerable item {item!r} asserted in "
                            f"`column_purposes.{key}` — this value renders into the machine doc as fact",
                        )
                    )

    return findings


def _is_gap_heading(heading: str) -> bool:
    return any(word in heading for word in ("gap", "warning", "caveat", "unknown", "not grounded"))


# --------------------------------------------------------------------------
# AS-10 — trust disclosures reach the artifact


_NEEDS_DISCLOSURE = {"draft", "stale", "contaminated"}


def check_artifact_trust(artifact: Mapping[str, Any], doc_statuses: Mapping[str, str]) -> list[Finding]:
    """A report built on a draft/stale/contaminated doc says so in the artifact.

    The transcript scrolls away; the artifact is what someone reads six
    months later. A warning that lived only in the chat is a warning that
    did not travel.
    """
    findings: list[Finding] = []
    semantics = artifact.get("semantics") or {}
    notes = " ".join(semantics.get("trust_notes") or []).lower()

    refs: list[str] = []
    for group in ("metrics", "dimensions"):
        for entry in semantics.get(group) or []:
            if entry.get("ref"):
                refs.append(entry["ref"])

    for ref in refs:
        status = doc_statuses.get(ref)
        if status in _NEEDS_DISCLOSURE and ref.lower() not in notes:
            findings.append(
                Finding(
                    "AS-10",
                    f"{ref} is {status} but no trust_note in the artifact mentions it",
                )
            )

    # FA-4: a blend key without an entity_ref is an improvised join.
    blend = artifact.get("blend")
    if blend:
        for i, key in enumerate(blend.get("keys") or []):
            if not key.get("entity_ref"):
                findings.append(
                    Finding("AS-10", f"blend.keys[{i}] has no entity_ref — the join was improvised")
                )

    return findings


# --------------------------------------------------------------------------
# CP-V1/CP-V2 / AS-7 — review-sync impact summary


_VERDICT = re.compile(r"^Verdict:\s*(BREAKING|ADDITIVE-ONLY)\b.*$", re.MULTILINE)
_MERGE_CLAIM = re.compile(r"\b(?:i|we)\s+(?:have\s+|will\s+)?merged?\b|\bmerging\s+now\b", re.IGNORECASE)


def check_review_summary(text: str) -> list[Finding]:
    """The review-sync S2 summary contract (skill spec §7 CP-V1/CP-V2).

    Pins: a verdict consistent with the body; breaking ranked first;
    rename candidates carrying *both* interpretations; undeclared
    references marked non-authoritative; no merge-performing language
    (the behavioral no-merge assertion is AS-7's, on git effects — this
    only catches a summary that *claims* the skill merged).
    """
    findings: list[Finding] = []
    # H2 sections only: the H1 is the summary's title, not a ranked section.
    h2 = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
    matches = list(h2.finditer(text))
    sections: dict[str, str] = {}
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[m.group(1).strip().lower()] = text[m.end() : end].strip()
    section_order = [h for h in sections]

    verdict_m = _VERDICT.search(text)
    if not verdict_m:
        findings.append(Finding("CP-V1", "no `Verdict:` line (BREAKING or ADDITIVE-ONLY)"))
    verdict = verdict_m.group(1) if verdict_m else None

    breaking_heading = next((h for h in section_order if h.startswith("breaking")), None)
    if verdict == "ADDITIVE-ONLY" and breaking_heading:
        findings.append(
            Finding("CP-V1", "verdict says ADDITIVE-ONLY but the summary has a Breaking section")
        )
    if verdict == "BREAKING" and not breaking_heading:
        findings.append(
            Finding("CP-V1", "verdict says BREAKING but the summary has no Breaking section")
        )

    # Breaking first: when present it is the first section — a reader who
    # stops after one section got the most important one.
    if breaking_heading and section_order[0] != breaking_heading:
        findings.append(
            Finding(
                "CP-V1",
                f"Breaking section ranked below {section_order[0]!r} — breaking changes come first",
            )
        )
    if breaking_heading and "contaminates" not in sections[breaking_heading].lower():
        findings.append(
            Finding(
                "CP-V1",
                "Breaking section names no contaminated docs — each breaking change "
                "carries its contamination fan-out and the route that carried it",
            )
        )

    rename_heading = next((h for h in section_order if "rename" in h), None)
    if rename_heading:
        # Bullet items span continuation lines; judge the whole item.
        items: list[list[str]] = []
        for line in sections[rename_heading].splitlines():
            # A bullet is "- " or "* " — a bare marker plus space, so a
            # bold "**…" continuation line is not mistaken for a new item.
            if re.match(r"[-*]\s", line.strip()):
                items.append([line])
            elif items and line.strip():
                items[-1].append(line)
        for item_lines in items:
            item = " ".join(l.strip() for l in item_lines).lower()
            if not ("renamed" in item and "removed" in item and "added" in item):
                findings.append(
                    Finding(
                        "CP-V1",
                        f"rename candidate lacks both interpretations (renamed vs removed+added): {item[:100]!r}",
                    )
                )

    undeclared_heading = next((h for h in section_order if "undeclared" in h), None)
    if undeclared_heading:
        blob = (undeclared_heading + " " + sections[undeclared_heading]).lower()
        if "non-authoritative" not in blob and "not authoritative" not in blob:
            findings.append(
                Finding(
                    "CP-V1",
                    "undeclared references are not marked non-authoritative — the scan "
                    "does not flag them and neither may the summary",
                )
            )

    if _MERGE_CLAIM.search(text):
        findings.append(
            Finding("CP-V2", "summary claims a merge was or will be performed — the skill never merges")
        )

    return findings


# --------------------------------------------------------------------------
# AS-18 / S1b — the queue-driven enrichment batch (D-101.4)


#: `customer-provided, <name>, <date>` — the citation an approved request
#: earns. The date is ISO because the ledger records one; a re-typed
#: "last week" would be exactly the un-sourceable prose S1b forbids.
_CUSTOMER_PROVIDED = re.compile(
    r"^customer-provided,\s*(?P<who>[^,]+?),\s*(?P<when>\d{4}-\d{2}-\d{2})\s*$"
)

#: The grades that mean "we looked at the estate and saw this". A doc
#: grounded no further than a proposal may not claim one.
_OBSERVED_GRADES = ("observed in", "app ddl", "customer doc:", "usage", "join_pairs")

#: The dressing CP-E5 names by name: an inference grading added beside a
#: customer-provided one to make a one-source list look like two.
_INFERRED = "inferred from column names"

#: A trailer, exactly as ledger §9 parses it.
_RESOLVES = re.compile(r"^CL-Resolves:\s*(?P<issue>[0-9a-fA-F-]{36})\s*$", re.MULTILINE)


def check_customer_provided_sources(
    sources: Sequence[str],
    *,
    grounded_beyond_proposal: bool,
) -> list[Finding]:
    """S1b's citation rule on one drafted doc.

    `grounded_beyond_proposal` is what the *author* claims they found —
    the caller passes what the evidence actually supported. The check is
    the pairing: a doc grounded no further than its proposal must carry
    the customer-provided citation **and nothing that reads as
    observation**, because a sources list is the only signal a reviewer
    has and inflating it destroys it (HLR §8 P4).
    """
    findings: list[Finding] = []
    entries = [str(s).strip() for s in sources]
    customer = [e for e in entries if e.lower().startswith("customer-provided")]

    if not customer:
        findings.append(
            Finding("AS-18", "no `customer-provided, <name>, <date>` source on a queue-driven draft")
        )
    for entry in customer:
        if not _CUSTOMER_PROVIDED.match(entry):
            findings.append(
                Finding(
                    "AS-18",
                    f"customer-provided source is not `customer-provided, <name>, <date>`: {entry!r} "
                    "— the name and ISO date come from what the ledger recorded, not from the request body",
                )
            )

    if not grounded_beyond_proposal:
        for entry in entries:
            low = entry.lower()
            if low.startswith("customer-provided"):
                continue
            if _INFERRED in low:
                findings.append(
                    Finding(
                        "CP-E5",
                        "a draft groundable no further than its proposal carries "
                        f"{_INFERRED!r} beside the customer-provided citation — "
                        "the dressing CP-E5 forbids: cite exactly that provenance and nothing better",
                    )
                )
            elif any(grade in low for grade in _OBSERVED_GRADES):
                findings.append(
                    Finding(
                        "CP-E5",
                        f"a draft groundable no further than its proposal claims observation: {entry!r} "
                        "— stated by someone who knows the business is never upgraded to observed by us",
                    )
                )
    return findings


def check_no_verbatim_submission(diff_text: str, proposals: Sequence[str]) -> list[Finding]:
    """DT-12's other half: the requester's words are not in the diff.

    Matched on **sentences**, not on tokens: a proposal and a well-drafted
    doc necessarily share vocabulary ("refund", "order"), and flagging
    that would make the rule unusable. What must not survive is a run of
    the requester's own prose — the doc is written in the KB's voice and
    *cites* the submission, so any long verbatim span is the failure.
    """
    findings: list[Finding] = []
    haystack = re.sub(r"\s+", " ", diff_text).lower()
    for proposal in proposals:
        for raw in re.split(r"(?<=[.!?;])\s+|\n+", str(proposal)):
            phrase = re.sub(r"\s+", " ", raw).strip().lower()
            # Short fragments collide by chance; a clause of this length
            # appearing intact is quotation, not coincidence.
            if len(phrase) < 40:
                continue
            if phrase in haystack:
                findings.append(
                    Finding(
                        "DT-12",
                        f"requester text appears verbatim in the diff: {phrase[:80]!r} — "
                        "the submission is drafting input, and the doc cites it rather than containing it",
                    )
                )
    return findings


def check_batch_pr_body(
    body: str,
    *,
    satisfied: Sequence[str],
    returned: Sequence[str],
) -> list[Finding]:
    """S5's queue-driven additions: the mapping, and exactly the right trailers.

    `satisfied` and `returned` are the issue ids the batch actually
    answered and actually handed back. The trailers are load-bearing —
    ledger §9 resolves on merge from these lines alone — so a trailer for
    a returned item closes a request nobody answered, and a missing
    trailer leaves an answered one open forever.
    """
    findings: list[Finding] = []
    trailers = [m.group("issue").lower() for m in _RESOLVES.finditer(body)]
    want = [str(i).lower() for i in satisfied]
    back = [str(i).lower() for i in returned]

    for issue in want:
        if issue not in trailers:
            findings.append(
                Finding("AS-18", f"no CL-Resolves trailer for satisfied request {issue} — merge would leave it open")
            )
    for issue in back:
        if issue in trailers:
            findings.append(
                Finding(
                    "AS-18",
                    f"CL-Resolves trailer for {issue}, which was returned to the queue — "
                    "merging would resolve a request the batch did not answer",
                )
            )
    for issue in trailers:
        if issue not in want and issue not in back:
            findings.append(Finding("AS-18", f"CL-Resolves trailer for {issue}, which is not in this batch"))
    if len(set(trailers)) != len(trailers):
        findings.append(Finding("AS-18", "a CL-Resolves trailer is repeated"))

    lowered = body.lower()
    if "request" not in lowered or not re.search(r"^\s*\|.*\|", body, re.MULTILINE):
        findings.append(
            Finding("AS-18", "no request → doc mapping in the PR body — a reviewer cannot tell which request each doc answers")
        )
    if back:
        # A returned item that the body does not name has been silently
        # dropped, which is the exact failure CP-E5 exists to prevent.
        for issue in back:
            if issue not in lowered:
                findings.append(
                    Finding("CP-E5", f"returned request {issue} is not named in the PR body — a silent drop")
                )
        if not re.search(r"unblock|would need|returned|blocked", lowered):
            findings.append(
                Finding("CP-E5", "returned items carry no statement of what evidence would unblock them")
            )
    return findings
