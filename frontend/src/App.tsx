import { useEffect, useState } from 'react'
import { HealthStatus } from './components/HealthStatus'
import { EngagementPage } from './pages/EngagementPage'
import { ReviewPage } from './pages/ReviewPage'

type Route = { page: 'engagements' } | { page: 'review'; reviewId: string }

// Two pages, so a hash router is enough - no routing dependency.
function parseRoute(hash: string): Route {
  const match = /^#\/reviews\/([A-Za-z0-9_-]+)$/.exec(hash)
  return match ? { page: 'review', reviewId: match[1] } : { page: 'engagements' }
}

export default function App() {
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.hash))

  useEffect(() => {
    const onChange = () => setRoute(parseRoute(window.location.hash))
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])

  const openReview = (reviewId: string) => {
    window.location.hash = `#/reviews/${reviewId}`
  }
  const back = () => {
    window.location.hash = '#/'
  }

  return (
    <main>
      <header>
        <h1>F&amp;D Tax Engagement Review Agent</h1>
        <p className="disclaimer">
          Decision support only — not tax advice. All data in this application is synthetic.
          Every finding requires review by a qualified professional.
        </p>
      </header>

      {route.page === 'review' ? (
        <ReviewPage reviewId={route.reviewId} onBack={back} />
      ) : (
        <EngagementPage onOpenReview={openReview} />
      )}

      <footer>
        <HealthStatus />
      </footer>
    </main>
  )
}
