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
