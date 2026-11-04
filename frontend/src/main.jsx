import { StrictMode, Suspense, lazy, useLayoutEffect } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'

const LegacyApp = lazy(() => import('./App.jsx'))
const FloorPreview = lazy(() => import('./floor/FloorPreview.jsx'))

function Routed() {
  const path = (window.location.pathname.replace(/\/+$/, '') || '/').toLowerCase()
  const isLegacyApp = path === '/legacy'
  const isObsoleteDesignPath = path === '/design' || path.startsWith('/design/')

  useLayoutEffect(() => {
    document.title = 'Haveli Ticket Management'
    if (isObsoleteDesignPath) window.location.replace('/')
  }, [isObsoleteDesignPath])

  if (isObsoleteDesignPath) return null
  if (isLegacyApp) {
    return (
      <Suspense fallback={<div role="status">Loading Haveli…</div>}>
        <LegacyApp />
      </Suspense>
    )
  }

  return (
    <Suspense fallback={<div role="status">Loading Haveli…</div>}>
      <FloorPreview />
    </Suspense>
  )
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <Routed />
  </StrictMode>,
)
