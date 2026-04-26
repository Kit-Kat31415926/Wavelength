import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { getUser } from '../lib/api'
import TraitRadar from '../components/TraitRadar'

export default function Portrait() {
  const navigate = useNavigate()
  const [profile, setProfile] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const user = JSON.parse(localStorage.getItem('wavelength_user') || '{}')

  useEffect(() => {
    if (!user.user_id) {
      setLoading(false)
      return
    }

    const loadProfile = async () => {
      try {
        const res = await getUser(user.user_id)
        if (!res.data.wavelengthlity) {
          return
        }
        setProfile(res.data)
      } catch (err) {
        const detail = err?.response?.data?.detail || ''
        if (err?.response?.status === 404 || detail.toLowerCase().includes('user not found')) {
          return
        }
        setError('Failed to load profile')
        console.error(err)
      } finally {
        setLoading(false)
      }
    }

    loadProfile()
  }, [])

  if (loading) return <div style={{ padding: '40px', textAlign: 'center' }}>Loading profile...</div>
  if (error) return <div style={{ padding: '40px', textAlign: 'center', color: 'var(--warm)' }}>{error}</div>
  if (!profile) return (
    <div style={{ textAlign: 'center', padding: '80px 40px' }}>
      <p style={{ fontSize: '18px', color: 'var(--gold)', marginBottom: '12px' }}>No profile yet</p>
      <p style={{ color: 'var(--text2)', marginBottom: '24px' }}>Complete your conversation so we can build your wavelength profile.</p>
      <button className="btn-primary" onClick={() => navigate('/converse')}>Start conversation</button>
    </div>
  )

  const w = profile.wavelengthlity
  const traitLabels = {
    openness: 'Openness',
    conscientiousness: 'Conscientiousness',
    extraversion: 'Extraversion',
    agreeableness: 'Agreeableness',
    emotional_stability: 'Emotional Stability',
    novelty_seeking: 'Novelty Seeking',
    security_need: 'Security Need'
  }

  return (
    <div style={{ padding: '40px 0' }}>
      <div className="portrait-container">
        {/* Left column */}
        <div className="portrait-left">
          <img
            src={profile.photo_url}
            alt={profile.name}
            className="portrait-photo"
          />
          <div>
            <div className="portrait-name">{profile.name}</div>
            {profile.age && <div style={{ fontSize: '14px', color: 'var(--text2)' }}>{profile.age} years old</div>}
          </div>

          <div className="portrait-summary">
            {w.summary}
          </div>

          <div className="portrait-section">
            <div className="portrait-section-title">Worldview</div>
            <p style={{ fontSize: '14px', color: 'var(--text2)', lineHeight: '1.6' }}>
              {w.worldview}
            </p>
          </div>

          <div className="portrait-section">
            <div className="portrait-section-title">Core Values</div>
            <div className="match-tags">
              {w.values.map((value, idx) => (
                <span key={idx} className="tag tag-gold">{value}</span>
              ))}
            </div>
          </div>

          <div className="portrait-section">
            <div className="portrait-section-title">Interests</div>
            <div className="match-tags">
              {w.interests.map((interest, idx) => (
                <span key={idx} className="tag">{interest}</span>
              ))}
            </div>
          </div>
        </div>

        {/* Right column */}
        <div>
          <TraitRadar traits={w.traits} />

          <div style={{ marginTop: '32px' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '16px' }}>
              <div className="stat-row">
                <span className="muted">Conflict Style</span>
                <span style={{ textTransform: 'capitalize' }}>{w.conflict_style}</span>
              </div>
              <div className="stat-row">
                <span className="muted">Communication</span>
                <span style={{ textTransform: 'capitalize' }}>{w.communication_register}</span>
              </div>
              <div className="stat-row">
                <span className="muted">Reasoning Style</span>
                <span style={{ textTransform: 'capitalize' }}>{w.reasoning_style}</span>
              </div>
            </div>
          </div>

          <div style={{ marginTop: '32px' }}>
            <div className="portrait-section-title">Energy Topics</div>
            <ul style={{ listStyle: 'none', fontSize: '14px' }}>
              {w.energy_topics.map((topic, idx) => (
                <li key={idx} style={{ paddingLeft: '16px', position: 'relative', marginBottom: '8px' }}>
                  <span style={{ position: 'absolute', left: 0, color: 'var(--gold)' }}>•</span>
                  {topic}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>

      <div style={{ marginTop: '60px', textAlign: 'center' }}>
        <button 
          className="btn-primary" 
          onClick={() => navigate('/matches')}
        >
          Find your matches →
        </button>
      </div>
    </div>
  )
}
