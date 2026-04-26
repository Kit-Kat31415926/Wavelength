import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { getPotentialMatches, getCompatibility, getSimulation } from '../lib/api'

import TraitRadar from '../components/TraitRadar'

export default function Matches() {
  const navigate = useNavigate()
  const [matches, setMatches] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [noProfile, setNoProfile] = useState(false)
  const [expandedMatch, setExpandedMatch] = useState(null)
  const [compatibility, setCompatibility] = useState(null)
  const [compatLoading, setCompatLoading] = useState(null)
  const [simulation, setSimulation] = useState(null)
  const [simLoading, setSimLoading] = useState(null)

  const user = JSON.parse(localStorage.getItem('wavelength_user') || '{}')

  const getTopMatches = (list) => {
    return [...(list || [])]
      .sort((a, b) => (b.overall_score || 0) - (a.overall_score || 0))
      .slice(0, 3)
  }

  useEffect(() => {
    if (!user.user_id) {
      setLoading(false)
      return
    }

    const loadMatches = async () => {
      try {
        const res = await getPotentialMatches(user.user_id, 3)
        setMatches(getTopMatches(res.data.matches || []))
      } catch (err) {
        const detail = err?.response?.data?.detail || ''
        if (err?.response?.status === 404 || detail.toLowerCase().includes('user not found') || detail.toLowerCase().includes('complete your interview')) {
          setNoProfile(true)
          return
        }
        setError(detail || 'Failed to load matches')
        console.error(err)
      } finally {
        setLoading(false)
      }
    }

    loadMatches()
  }, [])
  const handleShowCompatibility = async (matchId) => {
    setCompatLoading(matchId)
    try {
      const res = await getCompatibility({ user_id_a: user.user_id, user_id_b: matchId })
      setCompatibility(res.data.compatibility)
      setExpandedMatch(matchId)
      setSimulation(null)
    } catch (err) {
      setError('Failed to calculate compatibility')
      console.error(err)
    } finally {
      setCompatLoading(null)
    }
  }

  const handleSimulate = async (matchId) => {
    setSimLoading(matchId)
    try {
      const res = await getSimulation({ user_id_a: user.user_id, user_id_b: matchId })
      setSimulation(res.data.simulation)
    } catch (err) {
      setError('Failed to simulate conversation')
      console.error(err)
    } finally {
      setSimLoading(null)
    }
  }

  if (loading) {
    return (
      <div style={{ padding: '60px 24px', textAlign: 'center' }}>
        <p>Loading matches...</p>
      </div>
    )
  }

  return (
    <div style={{ padding: '40px 0' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '32px' }}>
        <h2>Potential Matches</h2>
      </div>

      {error && (
        <div style={{
          background: 'rgba(212, 130, 90, 0.1)',
          border: '1px solid rgba(212, 130, 90, 0.3)',
          color: '#d4825a',
          padding: '12px',
          borderRadius: 'var(--radius)',
          marginBottom: '24px',
          fontSize: '14px'
        }}>
          {error}
        </div>
      )}

      {matches.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '60px 40px', color: 'var(--text2)' }}>
          {noProfile ? (
            <>
              <p style={{ fontSize: '18px', color: 'var(--gold)', marginBottom: '12px' }}>No matches yet</p>
              <p style={{ marginBottom: '24px' }}>Complete your conversation first so we can find your people.</p>
              <button className="btn-primary" onClick={() => navigate('/converse')}>Start conversation</button>
            </>
          ) : (
            <>
              <p style={{ fontSize: '18px', color: 'var(--gold)', marginBottom: '12px' }}>No more matches</p>
              <p style={{ marginBottom: '24px' }}>You've gone through everyone available right now.</p>
            </>
          )}
        </div>
      ) : (
        <div className="match-list">
          {matches.map(match => (
            <div key={match.user_id}>
              <div className="match-card">
                <img src={match.photo_url} alt={match.name} className="match-photo" />
                <div className="match-info">
                  <div className="match-name">
                    {match.name} {match.age && <span className="muted">· {match.age}</span>}{match.gender && <span className="muted"> · {match.gender}</span>}
                  </div>
                  <div className="match-score-text">
                    Match score: {Math.round((match.overall_score || 0) * 100)}%
                  </div>
                  <div className="match-summary" style={{ fontSize: '13px', color: 'var(--text2)', marginTop: '4px' }}>
                    {match.summary || ''}
                  </div>
                  <div className="match-tags">
                    {(match.commonalities || []).slice(0, 4).map((item, idx) => (
                      <span key={idx} className="tag">{item}</span>
                    ))}
                  </div>
                  <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                    <button
                      className="btn-ghost"
                      onClick={() => handleShowCompatibility(match.user_id)}
                      disabled={compatLoading === match.user_id}
                    >
                      {compatLoading === match.user_id ? 'Analyzing...' : 'See compatibility'}
                    </button>
                    <button
                      className="btn-primary"
                      onClick={() => navigate(`/chat/${match.user_id}`)}
                      style={{ fontSize: '13px' }}
                    >
                      Message →
                    </button>
                  </div>
                </div>
                <div className="match-graph-wrap">
                  <TraitRadar
                    traits={match.wavelengthlity?.traits}
                    width="210px"
                    height="170px"
                    compact
                  />
                </div>
              </div>

              {/* Compatibility panel */}
              {expandedMatch === match.user_id && compatibility && (
                <div className="compatibility-panel">
                  <div className="compatibility-score">
                    <div className="compatibility-score-number">
                      {Math.round(compatibility.overall_score * 100)}%
                    </div>
                    <div className="score-bar" style={{ flex: 1 }}>
                      <div 
                        className="score-bar-fill" 
                        style={{ width: `${compatibility.overall_score * 100}%` }}
                      ></div>
                    </div>
                  </div>

                  <div className="compatibility-dimensions">
                    {Object.entries(compatibility.dimensions).map(([key, value]) => (
                      <div key={key} className="dimension-row">
                        <div className="dimension-label">
                          {key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}
                        </div>
                        <div className="dimension-bar">
                          <div 
                            className="dimension-bar-fill" 
                            style={{ width: `${value * 100}%` }}
                          ></div>
                        </div>
                        <div className="dimension-score">{Math.round(value * 100)}%</div>
                      </div>
                    ))}
                  </div>

                  <div className="compatibility-section">
                    <div className="compatibility-section-title">Strengths</div>
                    <ul className="compatibility-list">
                      {compatibility.strengths.map((strength, idx) => (
                        <li key={idx}>{strength}</li>
                      ))}
                    </ul>
                  </div>

                  <div className="compatibility-section">
                    <div className="compatibility-section-title">Friction Points</div>
                    <ul className="compatibility-list">
                      {compatibility.friction_points.map((friction, idx) => (
                        <li key={idx}>{friction}</li>
                      ))}
                    </ul>
                  </div>

                  <div className="compatibility-section">
                    <div className="compatibility-section-title">Analysis</div>
                    <div className="compatibility-reasoning">
                      {compatibility.reasoning}
                    </div>
                  </div>

                  <div className="compatibility-section">
                    <div className="compatibility-section-title">Conversation Starter</div>
                    <div className="conversation-starter">
                      "{compatibility.conversation_starter}"
                    </div>
                  </div>

                  <button
                    className="btn-ghost"
                    onClick={() => handleSimulate(match.user_id)}
                    disabled={simLoading === match.user_id}
                    style={{ marginTop: '16px' }}
                  >
                    {simLoading === match.user_id ? 'Simulating...' : 'Simulate a conversation →'}
                  </button>

                  {/* Simulation panel */}
                  {simulation && (
                    <div style={{ marginTop: '24px', paddingTop: '24px', borderTop: '1px solid var(--border)' }}>
                      <div className="compatibility-section-title">First Date Simulation</div>
                      <div className="dialogue">
                        {simulation.dialogue.map((exchange, idx) => (
                          <div 
                            key={idx} 
                            className={`dialogue-line ${idx % 2 === 0 ? 'speaker-a' : 'speaker-b'}`}
                          >
                            <div className="dialogue-speaker">{exchange.speaker}</div>
                            <div>{exchange.line}</div>
                          </div>
                        ))}
                      </div>
                      <div className="dialogue-insight">
                        <strong>Insight:</strong> {simulation.insight}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
