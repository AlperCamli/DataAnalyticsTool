/**
 * ULID generation (spec: 48-bit ms timestamp + 80 random bits, Crockford
 * base32). Job and snapshot ids sort by creation time lexicographically;
 * ~30 lines beats a dependency for something this fixed.
 */

import { randomBytes } from "node:crypto";

const ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";

export function ulid(time: number = Date.now()): string {
  let ts = "";
  let t = time;
  for (let i = 0; i < 10; i++) {
    ts = ALPHABET[t % 32]! + ts;
    t = Math.floor(t / 32);
  }
  const rand = randomBytes(16); // 16 chars × 5 bits; one random byte each
  let out = ts;
  for (let i = 0; i < 16; i++) {
    out += ALPHABET[rand[i]! % 32]!;
  }
  return out;
}
