/**
 * Validation tokens (MCP spec §5, M-2, MCP-R5): server-signed,
 * short-lived, bound to {statement sha256, system, snapshot_ref,
 * subject, profile}. Issuance happens at validate_sql (CP-4); this
 * module is also the **verification library** the CP-6 execution
 * gateway re-verifies with — every §5 binding check lives here, in one
 * place, so enforcement cannot drift from issuance.
 *
 * Signing keys live in ops Postgres (HMAC-SHA256, `signing_keys`).
 * Rotation = insert a new active row; verification accepts any stored
 * key by `kid`, so unexpired tokens survive rotation.
 */

import { createHmac, randomBytes, timingSafeEqual } from "node:crypto";
import pg from "pg";

export interface VtokenPayload {
  v: 1;
  statement_sha256: string;
  system: string;
  snapshot_ref: string;
  subject: string;
  profile: string;
  iat: number;
  exp: number;
}

export type VerifyResult =
  | { ok: true; payload: VtokenPayload }
  | { ok: false; code: "revalidate_required"; reason: string };

function b64url(data: Buffer | string): string {
  return Buffer.from(data).toString("base64url");
}

async function activeKey(pool: pg.Pool): Promise<{ kid: string; secret: string }> {
  const { rows } = await pool.query<{ kid: string; secret: string }>(
    `SELECT kid, secret FROM signing_keys WHERE active ORDER BY created_at DESC LIMIT 1`,
  );
  if (rows[0]) return rows[0];
  const kid = randomBytes(6).toString("hex");
  const secret = randomBytes(32).toString("base64url");
  await pool.query(`INSERT INTO signing_keys (kid, secret) VALUES ($1, $2)`, [kid, secret]);
  return { kid, secret };
}

async function keyByKid(pool: pg.Pool, kid: string): Promise<string | null> {
  const { rows } = await pool.query<{ secret: string }>(
    `SELECT secret FROM signing_keys WHERE kid = $1`,
    [kid],
  );
  return rows[0]?.secret ?? null;
}

function sign(secret: string, signingInput: string): Buffer {
  return createHmac("sha256", secret).update(signingInput).digest();
}

export async function issueValidationToken(
  pool: pg.Pool,
  binding: {
    statementSha256: string;
    system: string;
    snapshotRef: string;
    subject: string;
    profile: string;
  },
  ttlS: number,
  now: number = Date.now(),
): Promise<{ token: string; expiresAt: string }> {
  const key = await activeKey(pool);
  const iat = Math.floor(now / 1000);
  const payload: VtokenPayload = {
    v: 1,
    statement_sha256: binding.statementSha256,
    system: binding.system,
    snapshot_ref: binding.snapshotRef,
    subject: binding.subject,
    profile: binding.profile,
    iat,
    exp: iat + ttlS,
  };
  const header = b64url(JSON.stringify({ alg: "HS256", kid: key.kid }));
  const body = b64url(JSON.stringify(payload));
  const signature = sign(key.secret, `${header}.${body}`).toString("base64url");
  return {
    token: `${header}.${body}.${signature}`,
    expiresAt: new Date(payload.exp * 1000).toISOString(),
  };
}

/**
 * The §5 verification: signature ∧ statement hash ∧ subject ∧
 * snapshot_ref current ∧ not expired. Any mismatch →
 * `revalidate_required`, never silent re-validation.
 */
export async function verifyValidationToken(
  pool: pg.Pool,
  token: string,
  expected: {
    statementSha256: string;
    system: string;
    subject: string;
    currentSnapshotRef: string;
  },
  now: number = Date.now(),
): Promise<VerifyResult> {
  const fail = (reason: string): VerifyResult => ({ ok: false, code: "revalidate_required", reason });
  const parts = token.split(".");
  if (parts.length !== 3) return fail("malformed token");
  let header: { alg?: string; kid?: string };
  let payload: VtokenPayload;
  try {
    header = JSON.parse(Buffer.from(parts[0]!, "base64url").toString("utf-8"));
    payload = JSON.parse(Buffer.from(parts[1]!, "base64url").toString("utf-8"));
  } catch {
    return fail("malformed token");
  }
  if (header.alg !== "HS256" || typeof header.kid !== "string") return fail("malformed token header");
  const secret = await keyByKid(pool, header.kid);
  if (!secret) return fail("unknown signing key");
  const expectedSig = sign(secret, `${parts[0]}.${parts[1]}`);
  let providedSig: Buffer;
  try {
    providedSig = Buffer.from(parts[2]!, "base64url");
  } catch {
    return fail("malformed signature");
  }
  if (providedSig.length !== expectedSig.length || !timingSafeEqual(providedSig, expectedSig)) {
    return fail("signature mismatch");
  }
  if (payload.v !== 1) return fail("unknown token version");
  if (Math.floor(now / 1000) >= payload.exp) return fail("token expired");
  if (payload.statement_sha256 !== expected.statementSha256) {
    return fail("statement does not match the validated statement");
  }
  if (payload.subject !== expected.subject) return fail("token bound to a different subject");
  if (payload.system !== expected.system) return fail("token bound to a different system");
  if (payload.snapshot_ref !== expected.currentSnapshotRef) {
    return fail("snapshot advanced since validation");
  }
  return { ok: true, payload };
}
