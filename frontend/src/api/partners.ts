import { getAccessToken, renewAccessToken, signIn, signedInMomentsAgo } from '@/auth/oidc'

export type CheckStatus = 'VALID' | 'INVALID' | 'ERROR'

export type CheckResult = {
  id: string
  source: string
  status: CheckStatus
  checked_at: string
  /** Explanation for people, e.g. why the check gave ERROR. */
  message: string
  company_name: string | null
}

export type Partner = {
  id: string
  vat_number: string
  created_at: string
  latest_vies_check: CheckResult | null
}

/** An error the user can read. `code` comes from the backend, e.g. "duplicate_partner". */
export class ApiError extends Error {
  readonly status: number
  readonly code?: string

  constructor(message: string, status: number, code?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

const SERVER_UNAVAILABLE = 'The server is not reachable. Is the backend running?'
const TIMEOUT_MS = 15_000
// The backend waits up to 30 s for VIES (3 tries of 8 s), so wait a bit longer here.
const CHECK_TIMEOUT_MS = 40_000

const SESSION_ENDED = 'Your session has ended. Please sign in again.'
// Shown instead of sending the user to Keycloak again and again (see docs/authentication.md).
const SIGN_IN_NOT_ACCEPTED = 'The server does not accept your sign-in right now. Please try again in a moment.'

async function request<T>(path: string, init?: RequestInit, timeoutMs = TIMEOUT_MS): Promise<T> {
  const token = await getAccessToken()
  let response = await send(path, init, timeoutMs, token)

  if (response.status === 401 && token) {
    // The token may have expired a moment ago: renew it once and try again.
    const renewed = await renewAccessToken()
    if (renewed) {
      response = await send(path, init, timeoutMs, renewed)
      if (response.status === 401) {
        // A brand-new token is refused: signing in again would not help.
        const error = await toApiError(response)
        throw new ApiError(SIGN_IN_NOT_ACCEPTED, 401, error.code)
      }
    }
  }
  if (response.status === 401) {
    const error = await toApiError(response)
    if (signedInMomentsAgo()) throw new ApiError(SIGN_IN_NOT_ACCEPTED, 401, error.code)
    signIn().catch(() => {
      // Keycloak not reachable: the message below is all the user can get.
    })
    throw new ApiError(SESSION_ENDED, 401, error.code)
  }

  if (!response.ok) {
    throw await toApiError(response)
  }
  return (await response.json()) as T
}

async function send(
  path: string,
  init: RequestInit | undefined,
  timeoutMs: number,
  token: string | null,
): Promise<Response> {
  try {
    return await fetch(`/api/v1${path}`, {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...init?.headers,
      },
      // Never spin forever.
      signal: init?.signal ?? AbortSignal.timeout(timeoutMs),
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'TimeoutError') {
      throw new ApiError('The server took too long to answer. Please try again.', 0)
    }
    throw new ApiError(SERVER_UNAVAILABLE, 0)
  }
}

async function toApiError(response: Response): Promise<ApiError> {
  let body: unknown = null
  try {
    body = await response.json()
  } catch {
    // No JSON body, e.g. the dev proxy could not reach the backend.
  }

  const detail = (body as { detail?: unknown } | null)?.detail
  if (detail && typeof detail === 'object' && 'message' in detail) {
    const { message, code } = detail as { message: string; code?: string }
    return new ApiError(message, response.status, code)
  }
  if (response.status >= 500) {
    return new ApiError(SERVER_UNAVAILABLE, response.status)
  }
  return new ApiError(`The request failed (${response.status}). Please try again.`, response.status)
}

export function listPartners(): Promise<Partner[]> {
  return request<Partner[]>('/partners')
}

export function createPartner(vatNumber: string): Promise<Partner> {
  return request<Partner>('/partners', {
    method: 'POST',
    body: JSON.stringify({ vat_number: vatNumber }),
  })
}

/** Ask VIES now. ERROR is a normal result ("could not confirm"), not a thrown error. */
export function runViesCheck(partnerId: string): Promise<CheckResult> {
  return request<CheckResult>(
    `/partners/${encodeURIComponent(partnerId)}/checks/vies`,
    { method: 'POST' },
    CHECK_TIMEOUT_MS,
  )
}
