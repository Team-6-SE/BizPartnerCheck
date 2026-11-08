import { request, requestFile } from './client'

/** Event types of the security log (backend: app/security/events.py). */
export const SECURITY_EVENT_TYPES = {
  SIGN_IN: 'Sign-in',
  SIGN_IN_FAILED: 'Failed sign-in',
  SIGN_OUT: 'Sign-out',
  ACCOUNT_LOCKED: 'Account locked',
  PASSWORD_CHANGED: 'Password changed',
  PASSWORD_RESET_REQUESTED: 'Password reset requested',
  MFA_ENABLED: 'Two-factor set up',
  MFA_REMOVED: 'Two-factor removed',
  USER_CREATED: 'User created',
  USER_UPDATED: 'User changed',
  USER_DELETED: 'User deleted',
  ROLE_ASSIGNED: 'Role given',
  ROLE_REMOVED: 'Role taken away',
  API_TOKEN_CREATED: 'API token created',
  API_TOKEN_REVOKED: 'API token revoked',
  DATA_EXPORTED: 'Data exported',
} as const

export type SecurityEventType = keyof typeof SECURITY_EVENT_TYPES

export type SecurityEvent = {
  id: string
  occurred_at: string
  event_type: SecurityEventType | string
  /** One sentence for people, e.g. "Signed in with password and one-time code". */
  summary: string
  /** Who did it. */
  actor_email: string | null
  /** Whom it concerns, e.g. the user whose role was changed. */
  subject_email: string | null
  ip_address: string | null
  source: 'keycloak' | 'app' | string
}

export type SecurityEventPage = {
  items: SecurityEvent[]
  /** Pass as `before` to load older entries; null on the last page. */
  next_cursor: string | null
  /** ok: false when the newest Keycloak events could not be fetched. */
  sync: { ok: boolean; message: string | null; imported: number }
}

export type SecurityEventFilters = {
  eventType?: SecurityEventType
  /** Inclusive start, e.g. local midnight of the first day. */
  from?: Date
  /** Exclusive end, e.g. local midnight after the last day. */
  to?: Date
}

function query(filters: SecurityEventFilters, extra: Record<string, string> = {}): string {
  const params = new URLSearchParams(extra)
  if (filters.eventType) params.set('event_type', filters.eventType)
  if (filters.from) params.set('from', filters.from.toISOString())
  if (filters.to) params.set('to', filters.to.toISOString())
  const text = params.toString()
  return text ? `?${text}` : ''
}

export function listSecurityEvents(
  filters: SecurityEventFilters,
  before?: string | null,
  signal?: AbortSignal,
): Promise<SecurityEventPage> {
  const extra: Record<string, string> = { limit: '50' }
  if (before) extra.before = before
  return request<SecurityEventPage>(`/security-events${query(filters, extra)}`, { signal })
}

/** The filtered log as CSV file. The export itself is written to the log. */
export function exportSecurityEvents(filters: SecurityEventFilters): Promise<{ blob: Blob; filename: string }> {
  return requestFile(`/security-events/export${query(filters)}`, 60_000)
}
