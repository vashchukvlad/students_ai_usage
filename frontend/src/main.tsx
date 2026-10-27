import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './style.css'

function App() {
  const [status, setStatus] = useState('Checking API and database…')

  useEffect(() => {
    const controller = new AbortController()
    fetch('/api/health', { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error('API unavailable')
        const health = await response.json()
        if (health.status !== 'ok' || health.database !== 'ok') {
          throw new Error('Unexpected health response')
        }
        setStatus('API and database connected')
      })
      .catch(() => {
        if (!controller.signal.aborted) setStatus('API or database unavailable')
      })
    return () => controller.abort()
  }, [])

  return (
    <main>
      <p className="eyebrow">Student AI Usage</p>
      <h1>Understanding AI in student life</h1>
      <p>A dashboard for exploring AI usage, academic performance, and well-being.</p>
      <p role="status">{status}</p>
      <p>Survey visualizations are coming soon.</p>
    </main>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode><App /></StrictMode>,
)
