import { StrictMode, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { createRoot } from 'react-dom/client'
import { authenticate, getProfile, logout, refreshSession } from './api'
import type { Session } from './api'
import './style.css'

function App() {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [session, setSession] = useState<Session | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  useEffect(() => {
    let active = true
    refreshSession().then((value) => { if (active) setSession(value) })
      .catch(() => { /* No existing session: show sign-in. */ })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (!session) return
    const timer = window.setTimeout(() => {
      refreshSession().then(setSession).catch(() => {
        setSession(null)
        setError('Your session has expired. Please sign in again.')
      })
    }, Math.max(1000, (session.expires_in - 30) * 1000))
    return () => window.clearTimeout(timer)
  }, [session])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    const values = new FormData(form)
    setBusy(true); setError(''); setNotice('')
    try {
      setSession(await authenticate(mode, Object.fromEntries(values)))
      form.reset()
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Unable to sign in.')
    } finally { setBusy(false) }
  }

  async function signOut() {
    setBusy(true); setError(''); setNotice('')
    try {
      await logout(); setSession(null); setMode('login')
      setNotice('You have been signed out securely.')
    } catch { setError('Could not sign out. Please try again.') }
    finally { setBusy(false) }
  }

  async function checkSession() {
    setBusy(true); setError('')
    try {
      const user = await getProfile()
      setNotice(`Session verified for ${user.email}.`)
    } catch {
      setSession(null); setError('Your session has expired. Please sign in again.')
    } finally { setBusy(false) }
  }

  return (
    <div className="shell">
      <header className="header">
        <a className="brand" href="/" aria-label="Student AI Usage home"><span className="brand-icon">s.</span> student<span className="brand-light">/insights</span></a>
        <span className="header-note">A clearer view of student life</span>
      </header>
      <main className="layout">
        <section className="story" aria-label="About the dashboard">
          <span className="eyebrow"><span className="dot" /> THE STUDENT AI OBSERVATORY</span>
          <h1>Curiosity meets<br /><em>understanding.</em></h1>
          <p className="intro">Explore how AI is shaping the way we learn,<br className="desktop-break" /> achieve, and feel. Start with a fresh perspective.</p>
          <div className="illustration" aria-hidden="true">
            <div className="orbit orbit-one" /><div className="orbit orbit-two" />
            <div className="chart-card"><span>LEARNING, IN FOCUS</span><div className="bars">{[38, 58, 45, 78, 64, 91, 82].map((height, index) => <i key={index} style={{ height: `${height}%` }} />)}</div><div className="chart-label"><span>Small questions.</span><strong>Bigger perspectives ↗</strong></div></div>
            <div className="floating-tag">✦ &nbsp; Powered by your perspective</div>
          </div>
          <p className="story-foot">AI usage · Academic performance · Well-being</p>
        </section>
        <section className="auth-card" aria-label={session ? 'Your account' : 'Authentication'}>
          {loading ? <div role="status" className="loading">Restoring your session…</div> : session ? <>
            <span className="card-kicker">YOUR SPACE</span>
            <div className="avatar">{session.user.name.slice(0, 1).toUpperCase()}</div>
            <h2>Welcome, {session.user.name.split(' ')[0]}.</h2>
            <p className="subtitle">You’re signed in and ready to explore.</p>
            <div className="account-info"><span>YOUR ACCOUNT</span><strong>{session.user.email}</strong><p><span className="dot" /> Secure session active</p></div>
            <button className="primary" disabled={busy} onClick={checkSession}>Verify my session <span aria-hidden="true">↗</span></button>
            <button className="secondary" disabled={busy} onClick={signOut}>Sign out</button>
            <p className="coming-soon">Your dashboard is taking shape.<br />Survey visualizations are coming soon.</p>
          </> : <>
            <div className="tabs" aria-label="Account options">
              <button className={mode === 'login' ? 'active' : ''} onClick={() => { setMode('login'); setError(''); setNotice('') }} disabled={busy}>Sign in</button>
              <button className={mode === 'register' ? 'active' : ''} onClick={() => { setMode('register'); setError(''); setNotice('') }} disabled={busy}>Create account</button>
            </div>
            <span className="card-kicker">{mode === 'login' ? 'GOOD TO SEE YOU AGAIN' : 'A NEW PERSPECTIVE STARTS HERE'}</span>
            <h2>{mode === 'login' ? 'Welcome back.' : 'Make yourself at home.'}</h2>
            <p className="subtitle">{mode === 'login' ? 'Sign in to your student insights account.' : 'Create your account to join the exploration.'}</p>
            <form onSubmit={submit} key={mode}>
              {mode === 'register' && <label>Full name<input name="name" autoComplete="name" placeholder="Alex Morgan" required maxLength={80} pattern=".*\S.*" /></label>}
              <label>Email address<input name="email" type="email" autoComplete="email" placeholder="you@university.edu" required maxLength={254} /></label>
              <label>Password<input name="password" type="password" autoComplete={mode === 'login' ? 'current-password' : 'new-password'} placeholder={mode === 'login' ? 'Enter your password' : 'At least 8 characters'} minLength={8} maxLength={128} required /></label>
              {mode === 'register' && <p className="field-hint">Use at least 8 characters to keep your account safe.</p>}
              <button className="primary" disabled={busy} type="submit">{busy ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}<span aria-hidden="true">→</span></button>
            </form>
            <p className="switch-mode">{mode === 'login' ? 'New to the observatory?' : 'Already have an account?'} <button disabled={busy} onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError(''); setNotice('') }}>{mode === 'login' ? 'Create an account' : 'Sign in'}</button></p>
            <div className="secure-note"><span>♧</span> Your perspective is personal. Your account stays private.</div>
          </>}
          {error && <p className="message error" role="alert">{error}</p>}
          {notice && <p className="message success" role="status">{notice}</p>}
        </section>
      </main>
      <footer><span>Student AI Usage Dashboard</span><span>Built for understanding. Designed for you.</span></footer>
    </div>
  )
}

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>)
