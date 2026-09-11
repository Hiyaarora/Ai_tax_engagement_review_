import { HealthStatus } from './components/HealthStatus'

export default function App() {
  return (
    <main>
      <header>
        <h1>F&amp;D Tax Engagement Review Agent</h1>
        <p className="disclaimer">
          Decision support only — not tax advice. All data in this application is synthetic.
          Every finding requires review by a qualified professional.
        </p>
      </header>
      <HealthStatus />
    </main>
  )
}
