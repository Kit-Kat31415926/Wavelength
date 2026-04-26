import { useNavigate, useLocation } from 'react-router-dom'

export default function Landing() {
  const navigate = useNavigate()
  useLocation()
  const auth = JSON.parse(localStorage.getItem('wavelength_auth') || '{}')
  const isLoggedIn = Boolean(auth?.token)

  const scrollToFeatures = () => {
    document.getElementById('features')?.scrollIntoView({ behavior: 'smooth' })
  }

  return (
    <>
      <div className="hero">
        <h1>
          Find your people.<br />
          For real this time.
        </h1>
        <p className="hero-subtitle">
          A friend-finder built on genuine conversation.
        </p>
        <div className="hero-buttons">
          {!isLoggedIn && (
            <button className="btn-ghost" onClick={() => navigate('/auth')}>
              Create account / Login
            </button>
          )}
          <button className="btn-ghost" onClick={scrollToFeatures}>
            See how it works
          </button>
        </div>
      </div>

      <section id="features" className="container">
        <div className="features">
          <div className="feature-card">
            <h3>The Conversation</h3>
            <p>5 minutes of genuine conversation. No checkboxes, no swipes.</p>
          </div>
          <div className="feature-card">
            <h3>Your Portrait</h3>
            <p>An AI-built personality graph that captures how you truly are — not how you present.</p>
          </div>
          <div className="feature-card">
            <h3>Deep Matching</h3>
            <p>Find people who share your energy, values, and way of moving through the world.</p>
          </div>
        </div>

        <div className="footer">
          <br />
          <br />
          <br />
          Built for HackTech 2026
        </div>
      </section>
    </>
  )
}
