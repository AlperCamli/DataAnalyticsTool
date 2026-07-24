"""Human-readable benchmark report (R9) from an R8 results artifact.

Emits: the three-condition comparison (mean + range for selection
precision/recall, first-try executable, correctness); the MC-1 retrieval
recall table (per-journey selection recall, MC-1's metric); a per-case
breakdown; FM-2 evidence (visual_kind coverage vs the five-kind registry
table|line|bar|scorecard|pivot, plus any other:*); and SP-4/FM-4 evidence
(recurring cases). Correctness is reported with divergence detail (shape,
value-vs-checksum match) so a failed case shows *why*.
"""

from __future__ import annotations

from statistics import mean
from typing import Any, Iterable, Mapping

FIVE_KIND_REGISTRY = ["table", "line", "bar", "scorecard", "pivot"]  # formats spec §139, FM-2


def _fmt(x: float | None, pct: bool = False) -> str:
    if x is None:
        return "—"
    return f"{x*100:.0f}%" if pct else f"{x:.2f}"


def _range(vals: list[float]) -> str:
    if not vals:
        return "—"
    lo, hi = min(vals), max(vals)
    return f"{lo:.2f}" if lo == hi else f"{lo:.2f}–{hi:.2f}"


def _by_condition(journeys: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for j in journeys:
        out.setdefault(j["condition"], []).append(j)
    return out


def _mean_range(vals: list[float | None]) -> tuple[str, str]:
    clean = [v for v in vals if v is not None]
    if not clean:
        return "—", "—"
    return f"{mean(clean):.2f}", _range(clean)


def _condition_metrics(js: list[dict]) -> dict[str, Any]:
    prec = [j["selection"]["precision"] for j in js]
    rec = [j["selection"]["recall"] for j in js]
    ex = [1.0 if j["executable"]["first_try_executable"] else 0.0 for j in js]
    scored_corr = [j for j in js if j["correctness"]["scored"]]
    corr = [1.0 if j["correctness"]["correct"] else 0.0 for j in scored_corr]
    return {
        "n": len(js),
        "precision": _mean_range(prec),
        "recall": _mean_range(rec),
        "executable": (_fmt(mean(ex) if ex else None), _range(ex)),
        "correctness": (_fmt(mean(corr) if corr else None), _range(corr)) if corr else ("—", "—"),
        "corr_scored": len(scored_corr),
    }


def build_report(artifact: Mapping[str, Any]) -> str:
    run = artifact["run"]
    journeys = artifact["journeys"]
    cases_meta = {c["id"]: c for c in artifact.get("cases_meta", [])}
    conditions = run["conditions"]
    L: list[str] = []
    ap = L.append

    ap(f"# CVBuilder benchmark — {run['kind']} report")
    ap("")
    ap(f"- **suite** `{run['customer']}` v{run['suite_version']} · "
       f"**journey-prompt** {run['journey_prompt_version']} · "
       f"**backend** `{run['backend']}` · **model** `{run['model_id']}`")
    ap(f"- **reps** {run['reps']} · **journeys** {len(journeys)} · "
       f"**GA4 executions** {artifact.get('ga4_execution_count', 0)}")
    ap(f"- **snapshot_refs** " + ", ".join(f"{k} `{v[:16]}`" for k, v in run["snapshot_refs"].items()))
    ap(f"- **kb_refs** " + ", ".join(f"{k} `{str(v)[:16]}`" for k, v in run["kb_refs"].items()))
    ap(f"- **window** {run['started_at']} → {run['ended_at']}")
    ap(f"- _{run['notes']}_")
    ap("")

    # -- three-condition comparison ---------------------------------------
    ap("## Three-condition comparison (mean · range)")
    ap("")
    ap("| Condition | n | Selection precision | Selection recall | First-try executable | Result correctness |")
    ap("|---|---|---|---|---|---|")
    for cond in conditions:
        js = _by_condition(journeys).get(cond, [])
        if not js:
            continue
        m = _condition_metrics(js)
        ap(f"| {cond} | {m['n']} | {m['precision'][0]} · {m['precision'][1]} | "
           f"{m['recall'][0]} · {m['recall'][1]} | {m['executable'][0]} · {m['executable'][1]} | "
           f"{m['correctness'][0]} · {m['correctness'][1]} (n={m['corr_scored']}) |")
    ap("")

    # -- MC-1 retrieval recall table --------------------------------------
    ap("## MC-1 retrieval recall (per-journey selection recall)")
    ap("")
    ap("Recall of each case's `expected_objects` in the agent's executed statement(s). "
       "This is MC-1's metric (lexical retrieval, no embeddings — MC-1 default).")
    ap("")
    ap("| Case | " + " | ".join(conditions) + " |")
    ap("|---|" + "|".join(["---"] * len(conditions)) + "|")
    for cid in run["cases"]:
        cell = []
        for cond in conditions:
            recs = [j["selection"]["recall"] for j in journeys
                    if j["case_id"] == cid and j["condition"] == cond]
            cell.append(f"{mean(recs):.2f}" if recs else "—")
        if any(c != "—" for c in cell):
            ap(f"| {cid} | " + " | ".join(cell) + " |")
    ap("")

    # -- per-case breakdown -----------------------------------------------
    ap("## Per-case breakdown")
    ap("")
    ap("| Case | Condition | Precision | Recall | Exec | Correct | Divergence |")
    ap("|---|---|---|---|---|---|---|")
    for cid in run["cases"]:
        for cond in conditions:
            js = [j for j in journeys if j["case_id"] == cid and j["condition"] == cond]
            if not js:
                continue
            p = _mean_range([j["selection"]["precision"] for j in js])[0]
            r = _mean_range([j["selection"]["recall"] for j in js])[0]
            ex = _fmt(mean(1.0 if j["executable"]["first_try_executable"] else 0.0 for j in js), pct=True)
            corr_js = [j for j in js if j["correctness"]["scored"]]
            corr = (_fmt(mean(1.0 if j["correctness"]["correct"] else 0.0 for j in corr_js), pct=True)
                    if corr_js else "unscored")
            ap(f"| {cid} | {cond} | {p} | {r} | {ex} | {corr} | {_divergence(js)} |")
    ap("")

    # -- FM-2 evidence ----------------------------------------------------
    ap("## FM-2 evidence — visual_kind coverage")
    ap("")
    kinds = sorted({c["visual_kind"] for c in cases_meta.values()})
    base = [k for k in kinds if not k.startswith("other:")]
    others = [k for k in kinds if k.startswith("other:")]
    covered = [k for k in FIVE_KIND_REGISTRY if k in base]
    ap(f"- Five-kind registry (formats spec, FM-2): `{'`, `'.join(FIVE_KIND_REGISTRY)}`")
    ap(f"- Registry kinds exercised: {len(covered)}/5 — `{'`, `'.join(covered)}`")
    ap(f"- `other:*` used: {', '.join('`'+o+'`' for o in others) or 'none'}")
    ap("| Case | visual_kind |")
    ap("|---|---|")
    for cid in run["cases"]:
        if cid in cases_meta:
            ap(f"| {cid} | `{cases_meta[cid]['visual_kind']}` |")
    ap("")

    # -- SP-4 / FM-4 evidence ---------------------------------------------
    recurring = [c["id"] for c in cases_meta.values() if c.get("recurring")]
    ap("## SP-4 / FM-4 evidence — recurring cases")
    ap("")
    ap(f"- `recurring: true` count: **{len(recurring)}** of {len(cases_meta)} — "
       f"{', '.join(recurring)}")
    ap("- SP-4/FM-4 default: saved/parameterized re-runs are out of v1 (re-run = re-journey). "
       "Every case here is a recurring reporting need, so the suite exercises the "
       "re-journey path that SP-4 leaves as the v1 answer.")
    ap("")
    return "\n".join(L) + "\n"


def _divergence(js: list[dict]) -> str:
    """One-line correctness-divergence summary across a case's journeys."""
    notes = []
    for j in js:
        c = j["correctness"]
        if not c["scored"]:
            return "no same-run golden"
        if c["correct"]:
            notes.append("match")
            continue
        for leg in c["legs"]:
            if leg.get("correct") is False and leg.get("golden_shape") and leg.get("agent_shape"):
                gs, as_ = leg["golden_shape"], leg["agent_shape"]
                if gs != as_:
                    notes.append(f"{leg['system']} shape {tuple(as_)}≠{tuple(gs)}")
                elif leg.get("values_match") is False and leg.get("drift"):
                    notes.append(f"{leg['system']} int-drift")
                elif leg.get("values_match") is False:
                    notes.append(f"{leg['system']} values≠")
                elif leg.get("checksum_match") is False:
                    notes.append(f"{leg['system']} header≠ (data ok)")
    uniq = sorted(set(notes))
    return "; ".join(uniq[:3]) if uniq else "—"
