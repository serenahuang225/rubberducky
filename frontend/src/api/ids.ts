/** Stable-enough unique ids for outbox operation ids and idempotency keys. */

export function newId(): string {
  const cryptoApi = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto;
  if (cryptoApi?.randomUUID) {
    return cryptoApi.randomUUID();
  }
  // Last-resort fallback: timestamp + randomness, unique enough for local operation ids.
  return `id-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}
