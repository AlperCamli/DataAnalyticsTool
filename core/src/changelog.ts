/**
 * Sync PR title + changelog body (KB §9): batched, severity-ranked —
 * breaking first with contaminated docs and lineage paths, rename
 * candidates with both interpretations, additive-with-note items,
 * undeclared possible references last. Pure string assembly over the
 * Python stages' outputs; deterministic (SY-1/SO-12) — sorted
 * everywhere, no wall clock, no run ids in the body.
 */

export interface FinalizedDiff {
  system: string;
  empty: boolean;
  added: DiffObject[];
  removed: DiffObject[];
  changed_structural: DiffObject[];
  changed_metadata_only: DiffObject[];
  severity_finalized?: boolean;
}

export interface DiffObject {
  identity: { kind: string; schema: string; name: string };
  classification: string;
  severity?: string;
  sub_diffs?: { change: string; severity: string; detail: Record<string, unknown>; downgraded?: string }[];
  rename_candidates?: {
    from_column: string;
    to_column: string;
    type: string;
    ordinal: number;
    interpretations: string[];
  }[];
  metadata_changes?: string[];
}

export interface ScanResult {
  contaminated: {
    doc: string;
    status_was: string;
    contamination: { object: string; change: string; detail: string; path?: string[] };
    reasons: { object: string; change: string; detail: string; path?: string[] }[];
  }[];
  stale: { doc: string; status_was: string; objects: string[] }[];
  undeclared_references: { doc: string; object: string }[];
  breaking: Record<string, { change: string; detail: string }>;
  additive_changed: string[];
}

export interface ChangelogInput {
  diffs: FinalizedDiff[];
  scan: ScanResult | null;
  wheel: { fromVersion: string | null; toVersion: string } | null;
  excluded: { system: string; reason: string }[];
}

/**
 * Neutralize a snapshot-derived string before it is interpolated into the
 * PR markdown (review F4 / D-66 point 2). Object/column names and
 * view-diff detail are attacker-influenceable, yet the reviewer trusts
 * this PR — a crafted name must not break out of its code span, forge a
 * heading, or fire an @mention. Collapse newlines, defuse code-span
 * backticks, and HTML-encode the inline-markdown metacharacters
 * (`< > @ [ ] * |`) so any injected control sequence renders as inert
 * text. A strict no-op on ordinary identifiers/paths (they carry none of
 * these), so the deterministic changelog (SO-12) is byte-unchanged.
 * Exported since CP-4: list_gaps renders ledger text through the same
 * neutralization (LED-R5 — same injection class as F4).
 */
export function neutralize(value: unknown): string {
  return String(value)
    .replace(/[\r\n]+/g, " ")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/`/g, "'")
    .replace(/@/g, "&#64;")
    .replace(/\[/g, "&#91;")
    .replace(/\]/g, "&#93;")
    .replace(/\*/g, "&#42;")
    .replace(/\|/g, "&#124;");
}

const fqnOf = (system: string, o: DiffObject) =>
  neutralize(`${system}.${o.identity.schema}.${o.identity.name}`);

export function countBreaking(input: ChangelogInput): number {
  return input.scan ? Object.keys(input.scan.breaking).length : 0;
}

export function countAdditive(input: ChangelogInput): number {
  let count = 0;
  for (const diff of input.diffs) {
    count += diff.added.length;
    count += diff.changed_structural.filter((o) => o.severity !== "breaking").length;
  }
  return count;
}

export function buildTitle(input: ChangelogInput): string {
  const systems = input.diffs
    .filter((d) => !d.empty)
    .map((d) => d.system)
    .sort();
  if (systems.length === 0 && input.wheel) {
    return `sync: 0 breaking, 0 additive (wheel-only update to ${neutralize(input.wheel.toVersion)})`;
  }
  return `sync: ${countBreaking(input)} breaking, ${countAdditive(input)} additive across ${systems.map(neutralize).join(", ")}`;
}

export function buildLabels(input: ChangelogInput): string[] {
  // SO-B default: label only, the product never merges.
  return countBreaking(input) === 0 ? ["sync:additive-only"] : [];
}

export function buildBody(input: ChangelogInput): string {
  const lines: string[] = [];
  const scan = input.scan;

  if (input.wheel) {
    lines.push(
      `> Leads with a vendored validation wheel update ` +
        `${neutralize(input.wheel.fromVersion ?? "(none)")} → ${neutralize(input.wheel.toVersion)} (sync spec §10); ` +
        `this PR's KB CI already runs the new wheel.`,
      "",
    );
  }
  if (!scan) {
    lines.push("Wheel-only run: no drift pending; carry forced by a manual sync.");
    return lines.join("\n") + "\n";
  }

  const contaminatedByObject = new Map<string, { doc: string; path?: string[] }[]>();
  for (const c of scan.contaminated) {
    for (const reason of c.reasons) {
      const list = contaminatedByObject.get(reason.object) ?? [];
      list.push({ doc: c.doc, ...(reason.path ? { path: reason.path } : {}) });
      contaminatedByObject.set(reason.object, list);
    }
  }

  const breakingFqns = Object.keys(scan.breaking).sort();
  if (breakingFqns.length > 0) {
    lines.push("## Breaking", "");
    for (const fqn of breakingFqns) {
      const { detail } = scan.breaking[fqn]!;
      lines.push(`- \`${neutralize(fqn)}\` — ${neutralize(detail)}`);
      const docs = (contaminatedByObject.get(fqn) ?? []).sort((a, b) =>
        a.doc < b.doc ? -1 : 1,
      );
      for (const hit of docs) {
        lines.push(
          hit.path
            ? `  - contaminates \`${neutralize(hit.doc)}\` (lineage path: ${hit.path.map((p) => `\`${neutralize(p.slice(0, 19))}…\``).join(" → ")})`
            : `  - contaminates \`${neutralize(hit.doc)}\` (declared dependency)`,
        );
      }
    }
    lines.push("");
  }

  const renames: string[] = [];
  for (const diff of [...input.diffs].sort((a, b) => (a.system < b.system ? -1 : 1))) {
    for (const obj of diff.changed_structural) {
      for (const candidate of obj.rename_candidates ?? []) {
        renames.push(
          `- \`${fqnOf(diff.system, obj)}\`: \`${neutralize(candidate.from_column)}\` → ` +
            `\`${neutralize(candidate.to_column)}\` (type ${neutralize(candidate.type)}, ordinal ${candidate.ordinal}) — ` +
            `either **${neutralize(candidate.interpretations[0])}** or **${neutralize(candidate.interpretations[1])}**; ` +
            `the removal is breaking under both readings`,
        );
      }
    }
  }
  if (renames.length > 0) {
    lines.push("### Rename candidates", "", ...renames.sort(), "");
  }

  const withNote: string[] = [];
  const additive: string[] = [];
  const metadataOnly: string[] = [];
  for (const diff of [...input.diffs].sort((a, b) => (a.system < b.system ? -1 : 1))) {
    for (const obj of diff.added) {
      additive.push(`- \`${fqnOf(diff.system, obj)}\` — added (${neutralize(obj.identity.kind)})`);
    }
    for (const obj of diff.changed_structural) {
      if (obj.severity === "breaking") continue;
      const fqn = fqnOf(diff.system, obj);
      const subs = (obj.sub_diffs ?? [])
        .map((s) => {
          const target = s.detail.column ?? s.detail.key ?? s.detail.stat ?? "";
          const note = s.downgraded ? " (downgraded per §7 note ³: output columns and mappings unchanged)" : "";
          return `${neutralize(s.change)}${target ? `: ${neutralize(target)}` : ""}${note}`;
        })
        .join("; ");
      if (obj.severity === "additive-with-note") withNote.push(`- \`${fqn}\` — ${subs}`);
      else additive.push(`- \`${fqn}\` — ${subs}`);
    }
    for (const obj of diff.changed_metadata_only) {
      metadataOnly.push(
        `- \`${fqnOf(diff.system, obj)}\` — ${(obj.metadata_changes ?? []).map(neutralize).join(", ")}`,
      );
    }
  }
  if (withNote.length > 0) lines.push("## Additive (with note)", "", ...withNote.sort(), "");
  if (additive.length > 0) lines.push("## Additive", "", ...additive.sort(), "");
  if (metadataOnly.length > 0) {
    lines.push("## Metadata-only (regenerated, never scanned)", "", ...metadataOnly.sort(), "");
  }

  if (scan.stale.length > 0) {
    lines.push("## Docs marked stale", "");
    for (const s of [...scan.stale].sort((a, b) => (a.doc < b.doc ? -1 : 1))) {
      lines.push(`- \`${neutralize(s.doc)}\` (additive drift on ${s.objects.map((o) => `\`${neutralize(o)}\``).join(", ")})`);
    }
    lines.push("");
  }

  if (input.excluded.length > 0) {
    lines.push("## Systems excluded from this run (SY-6)", "");
    for (const e of [...input.excluded].sort((a, b) => (a.system < b.system ? -1 : 1))) {
      lines.push(`- \`${neutralize(e.system)}\` — ${neutralize(e.reason)}`);
    }
    lines.push("");
  }

  if (scan.undeclared_references.length > 0) {
    lines.push(
      "## Undeclared possible references",
      "",
      "Body-text mentions of changed objects in docs that do not declare them —",
      "surfaced for review, never auto-flagged (KB §6 step 5).",
      "",
    );
    for (const u of scan.undeclared_references) {
      lines.push(`- \`${neutralize(u.doc)}\` mentions \`${neutralize(u.object)}\``);
    }
    lines.push("");
  }

  return lines.join("\n").replace(/\n+$/, "") + "\n";
}
