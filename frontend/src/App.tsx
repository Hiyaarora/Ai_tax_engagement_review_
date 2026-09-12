import { useEffect, useState } from 'react'
import { HomePage } from './pages/HomePage'
import { WorkspacePage } from './pages/WorkspacePage'
import { parseRoute, type Route } from './routes'

export default function App() {
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.hash))

  useEffect(() => {
    const onChange = () => setRoute(parseRoute(window.location.hash))
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])

  const go = (hash: string) => {
    window.location.hash = hash
  }

  return (
    <main>
      <header className="masthead">
        <h1>F&amp;D Tax Engagement Review Agent</h1>
        <p className="notice" role="note">
          AI decision support • Synthetic/demo data • Human review required.{' '}
          <span className="notice__legal">Not tax advice.</span>
        </p>
      </header>

      {route.page === 'workspace' ? (
        <WorkspacePage
          engagementId={route.engagementId}
          step={route.step}
          reviewId={route.reviewId}
          onNavigate={(step, reviewId) =>
            go(`#/e/${route.engagementId}/${step}${reviewId ? `/${reviewId}` : ''}`)
          }
          onHome={() => go('#/')}
        />
      ) : (
        <HomePage onOpen={(id) => go(`#/e/${id}/documents`)} />
      )}

      <footer className="footer">Powered by Microsoft Foundry</footer>
    </main>
  )
}
