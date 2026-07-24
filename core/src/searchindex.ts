/**
 * Deterministic lexical + structured search (M-6): exact FQN/alias
 * match ≫ title match ≫ front-matter field match ≫ body lexical score;
 * entity and metric hits boosted above raw tables (they are the routing
 * layer). No embeddings, no model artifacts. Results are
 * visibility-filtered before ranking (M-4 — filtered hits are simply
 * absent), and repo-level docs surface with one-liners derived from
 * title/first line only (KB-F resolution, MCP-R15 — matched body text
 * is never echoed).
 */

import type { KbDoc, KbState } from "./kbread.js";
import { pathVisible } from "./visibility.js";

export type RefKind = "entity" | "metric" | "table" | "view" | "api_object" | "doc";

export interface IndexEntry {
  refKind: RefKind;
  path: string;
  fqn: string | null;
  title: string;
  oneLiner: string;
  aliases: string[];
  fmTokens: Set<string>;
  bodyTokens: Set<string>;
  routingBoost: number;
}

export interface SearchHit {
  entry: IndexEntry;
  tier: number;
  score: number;
}

const TOKEN_RE = /[a-z0-9_][a-z0-9_.-]*/g;

export function tokenize(text: string): string[] {
  return (text.toLowerCase().match(TOKEN_RE) ?? []).filter((t) => t.length > 1);
}

/** Function words carry no lexical signal; query tokens drop them so a
 * lone "for"/"of" can never manufacture a match (deterministic, M-6). */
const QUERY_STOPWORDS = new Set([
  "an", "the", "of", "by", "for", "in", "on", "to", "and", "or", "with",
  "per", "at", "from", "into", "is", "are", "was", "be", "how", "what",
  "which", "who", "show", "me", "my", "our", "their", "get", "list", "all",
]);

function kindToRef(kind: string): RefKind {
  if (kind === "table") return "table";
  if (kind === "view" || kind === "materialized_view") return "view";
  if (kind.startsWith("api_")) return "api_object";
  return "doc";
}

function entryFor(doc: KbDoc, ws: KbState): IndexEntry | null {
  const fm = doc.fm ?? {};
  const aliases = Array.isArray(fm.aliases)
    ? (fm.aliases as unknown[]).filter((a): a is string => typeof a === "string").map((a) => a.toLowerCase())
    : [];
  const fmFields: string[] = [];
  for (const value of Object.values(fm)) {
    if (typeof value === "string") fmFields.push(value);
  }
  const base = {
    path: doc.path,
    title: doc.title,
    oneLiner: doc.oneLiner,
    aliases,
    fmTokens: new Set(tokenize(fmFields.join(" "))),
    bodyTokens: new Set(tokenize(doc.body)),
  };
  if (doc.docClass === "entity") {
    return { ...base, refKind: "entity", fqn: null, routingBoost: 2 };
  }
  if (doc.docClass === "metric") {
    return { ...base, refKind: "metric", fqn: null, routingBoost: 2 };
  }
  if (doc.docClass === "machine-object" && typeof fm.object === "string") {
    return { ...base, refKind: kindToRef(String(fm.kind ?? "")), fqn: fm.object, routingBoost: 0 };
  }
  if (doc.docClass === "human-object" && typeof fm.object === "string") {
    const kind = ws.machineByFqn.get(fm.object)?.kind ?? "";
    return { ...base, refKind: kindToRef(kind), fqn: fm.object, routingBoost: 1 };
  }
  if (doc.docClass === "machine-group" || doc.docClass === "human-group" || doc.docClass === "machine-index") {
    return { ...base, refKind: "doc", fqn: null, routingBoost: 0 };
  }
  // Repo-level docs (index.md, conventions.md, _notes.md, lineage notes):
  // KB-F — indexed, visibility-checked, served without a trust block.
  return { ...base, refKind: "doc", fqn: null, routingBoost: 0 };
}

export function buildIndex(ws: KbState): IndexEntry[] {
  const entries: IndexEntry[] = [];
  for (const doc of ws.docs.values()) {
    const entry = entryFor(doc, ws);
    if (entry) entries.push(entry);
  }
  entries.sort((a, b) => (a.path < b.path ? -1 : a.path > b.path ? 1 : 0));
  return entries;
}

/**
 * Deterministic ranking (M-6). Tier 0: exact FQN/alias; tier 1: title;
 * tier 2: front-matter field; tier 3: body lexical. Within a tier:
 * match count, then routing boost (entities/metrics over raw tables),
 * then path — total order, no randomness.
 */
export function search(
  index: IndexEntry[],
  scopes: string[],
  query: string,
  limit: number,
): SearchHit[] {
  const q = query.trim().toLowerCase();
  const tokens = tokenize(q).filter((t) => !QUERY_STOPWORDS.has(t));
  if (tokens.length === 0) return [];
  const hits: SearchHit[] = [];
  for (const entry of index) {
    if (!pathVisible(scopes, entry.path)) continue;
    let tier = -1;
    let matches = 0;
    const fqnLower = entry.fqn?.toLowerCase() ?? null;
    if ((fqnLower && (q === fqnLower || tokens.includes(fqnLower))) || entry.aliases.includes(q)) {
      tier = 0;
      matches = tokens.length;
    } else {
      const titleTokens = new Set(tokenize(entry.title));
      const titleMatches = tokens.filter((t) => titleTokens.has(t)).length;
      const nameToken = fqnLower ? fqnLower.split(".").pop()! : "";
      const nameMatches = nameToken && tokens.includes(nameToken) ? 1 : 0;
      if (titleMatches > 0 || nameMatches > 0) {
        tier = 1;
        matches = titleMatches + nameMatches;
      } else {
        const fmMatches = tokens.filter((t) => entry.fmTokens.has(t)).length;
        if (fmMatches > 0) {
          tier = 2;
          matches = fmMatches;
        } else {
          const bodyMatches = tokens.filter((t) => entry.bodyTokens.has(t)).length;
          if (bodyMatches === tokens.length || (tokens.length > 2 && bodyMatches >= tokens.length - 1)) {
            tier = 3;
            matches = bodyMatches;
          }
        }
      }
    }
    if (tier === -1) continue;
    hits.push({ entry, tier, score: (3 - tier) * 1000 + matches * 10 + entry.routingBoost });
  }
  hits.sort((a, b) => b.score - a.score || (a.entry.path < b.entry.path ? -1 : 1));
  return hits.slice(0, limit);
}
