export type User = { id: string; email: string; name: string }
export type Session = { access_token: string; expires_in: number; user: User }

let accessToken: string | null = null
let refreshPromise: Promise<Session> | null = null

async function parse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(typeof body?.detail === 'string' ? body.detail : 'Something went wrong. Please try again.')
  }
  return response.status === 204 ? undefined as T : response.json()
}

export async function authenticate(mode: 'login' | 'register', data: object): Promise<Session> {
  const session = await parse<Session>(await fetch(`/api/auth/${mode}`, {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
  }))
  accessToken = session.access_token
  return session
}

export function refreshSession(): Promise<Session> {
  if (!refreshPromise) {
    refreshPromise = fetch('/api/auth/refresh', { method: 'POST', credentials: 'same-origin' })
      .then(parse<Session>)
      .then((session) => { accessToken = session.access_token; return session })
      .catch((error: unknown) => { accessToken = null; throw error })
      .finally(() => { refreshPromise = null })
  }
  return refreshPromise
}

export async function getProfile(): Promise<User> {
  const request = () => fetch('/api/auth/me', {
    headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
  })
  let response = await request()
  if (response.status === 401) {
    await refreshSession()
    response = await request()
  }
  return parse<User>(response)
}

export async function logout(): Promise<void> {
  // Settle any in-flight rotation before revoking the cookie's current session.
  if (refreshPromise) await refreshPromise.catch(() => undefined)
  await parse<void>(await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' }))
  accessToken = null
}

export type Column = { name: string; label: string; kind: 'number' | 'category' | 'text'; values: string[] }
export type DashboardFilters = { major: string; year: string; burnout: string; metric: string; group_by: string; page: number }
export type DashboardData = {
  status: 'ready'
  dataset: { checksum: string; source_url: string; filename: string; imported_at: string; row_count: number; columns: Column[] }
  metric: string; group_by: string
  summary: { count: number; measured: number; average: number | null; minimum: number | null; maximum: number | null; ai_hours: number | null; pre_gpa: number | null; post_gpa: number | null; gpa_change: number | null; high_burnout: number }
  groups: { name: string | null; count: number; average: number | null; ai_hours: number | null; pre_gpa: number | null; post_gpa: number | null }[]
  histogram: { from: number; to: number; count: number }[]
  rows: { row_number: number; data: Record<string, string | number | null> }[]
  page: number; pages: number
}
export class SessionExpired extends Error {}

export async function getDashboard(filters: DashboardFilters): Promise<DashboardData | { status: 'empty'; source_url: string }> {
  const query = new URLSearchParams()
  Object.entries(filters).forEach(([key, value]) => { if (value !== '') query.set(key, String(value)) })
  const request = () => fetch(`/api/dashboard?${query}`, {
    headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
  })
  let response = await request()
  if (response.status === 401) {
    try { await refreshSession() } catch { throw new SessionExpired('Your session has expired. Please sign in again.') }
    response = await request()
    if (response.status === 401) throw new SessionExpired('Your session has expired. Please sign in again.')
  }
  return parse<DashboardData | { status: 'empty'; source_url: string }>(response)
}
