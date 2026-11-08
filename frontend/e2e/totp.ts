import { createHmac } from 'node:crypto'

/**
 * The 6-digit code an authenticator app would show (RFC 6238, SHA-1, 30 s).
 *
 * `secret` is the raw secret from Keycloak's hidden `#totpSecret` field on the
 * set-up page (the QR code carries the same secret, base32-encoded).
 */
export function totpCode(secret: string, at = Date.now()): string {
  const counter = Buffer.alloc(8)
  counter.writeBigUInt64BE(BigInt(Math.floor(at / 1000 / 30)))
  const hash = createHmac('sha1', Buffer.from(secret, 'utf8')).update(counter).digest()
  const offset = hash[hash.length - 1] & 0xf
  return ((hash.readUInt32BE(offset) & 0x7fffffff) % 1_000_000).toString().padStart(6, '0')
}

/** Milliseconds until the next code: Keycloak accepts each code only once. */
export function msUntilNextCode(at = Date.now()): number {
  return 30_000 - (at % 30_000) + 200
}
