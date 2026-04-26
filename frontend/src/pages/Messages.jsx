import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { getConversations, sendMeetupFeedback } from '../lib/api'

export default function Messages() {
  const navigate = useNavigate()
  const [conversations, setConversations] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [feedbackOpenFor, setFeedbackOpenFor] = useState(null)
  const [feedbackForms, setFeedbackForms] = useState({})
  const [submittingFor, setSubmittingFor] = useState(null)
  const [feedbackSuccess, setFeedbackSuccess] = useState({})

  const auth = JSON.parse(localStorage.getItem('wavelength_auth') || '{}')
  const isLoggedIn = Boolean(auth?.token)
  const user = JSON.parse(localStorage.getItem('wavelength_user') || '{}')

  useEffect(() => {
    if (!isLoggedIn || !user.user_id) {
      setLoading(false)
      return
    }

    const load = async () => {
      try {
        const res = await getConversations(user.user_id)
        setConversations(res.data.conversations || [])
      } catch (err) {
        setError('Failed to load conversations')
        console.error(err)
      } finally {
        setLoading(false)
      }
    }

    load()
  }, [isLoggedIn, user.user_id])

  if (loading) {
    return <div style={{ padding: '60px 24px', textAlign: 'center' }}>Loading messages...</div>
  }

  if (!isLoggedIn) {
    return (
      <div style={{ padding: '40px 0', maxWidth: '640px', margin: '0 auto' }}>
        <h2 style={{ marginBottom: '24px' }}>Messages</h2>
        <div style={{ textAlign: 'center', color: 'var(--text2)', padding: '40px 0' }}>
          <p style={{ fontSize: '18px', color: 'var(--gold)', marginBottom: '10px' }}>You are not logged in</p>
          <p style={{ fontSize: '14px', marginBottom: '20px' }}>
            Log in to view your conversations and message your matches.
          </p>
          <button className="btn-primary" onClick={() => navigate('/auth')}>
            Login
          </button>
        </div>
      </div>
    )
  }

  const getFormState = (otherUserId) => {
    return feedbackForms[otherUserId] || {
      met: 'yes',
      chemistry_rating: 4,
      communication_rating: 4,
      safety_rating: 5,
      would_meet_again: 'yes',
      notes: '',
    }
  }

  const updateForm = (otherUserId, patch) => {
    setFeedbackForms((prev) => ({
      ...prev,
      [otherUserId]: {
        ...getFormState(otherUserId),
        ...patch,
      },
    }))
  }

  const handleSubmitFeedback = async (otherUserId) => {
    const form = getFormState(otherUserId)
    setSubmittingFor(otherUserId)
    setError('')
    try {
      const payload = {
        from_user_id: user.user_id,
        to_user_id: otherUserId,
        met: form.met === 'yes',
        notes: form.notes?.trim() || null,
      }

      if (form.met === 'yes') {
        payload.chemistry_rating = Number(form.chemistry_rating)
        payload.communication_rating = Number(form.communication_rating)
        payload.safety_rating = Number(form.safety_rating)
        payload.would_meet_again = form.would_meet_again === 'yes'
      }

      await sendMeetupFeedback(payload)
      setFeedbackSuccess((prev) => ({ ...prev, [otherUserId]: 'Feedback saved. Future suggestions will adapt.' }))
      setFeedbackOpenFor(null)
    } catch (err) {
      setError(err?.response?.data?.detail || 'Failed to save meetup feedback')
      console.error(err)
    } finally {
      setSubmittingFor(null)
    }
  }

  return (
    <div style={{ padding: '40px 0', maxWidth: '640px', margin: '0 auto' }}>
      <h2 style={{ marginBottom: '24px' }}>Messages</h2>

      {error && (
        <div style={{
          background: 'rgba(212, 130, 90, 0.1)',
          border: '1px solid rgba(212, 130, 90, 0.3)',
          color: '#d4825a',
          padding: '12px',
          borderRadius: 'var(--radius)',
          marginBottom: '16px',
          fontSize: '14px',
        }}>
          {error}
        </div>
      )}

      {conversations.length === 0 ? (
        <div style={{ textAlign: 'center', color: 'var(--text2)', padding: '40px 0' }}>
          <p>No conversations yet.</p>
          <p style={{ fontSize: '14px', marginTop: '8px' }}>
            Find a match and click <strong>Message →</strong> to start chatting.
          </p>
          <button
            className="btn-primary"
            style={{ marginTop: '20px' }}
            onClick={() => navigate('/matches')}
          >
            Discover matches
          </button>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
          {conversations.map((conv) => {
            const other = conv.other_user
            const last = conv.last_message
            const isFromMe = last.from_user_id === user.user_id
            const preview = `${isFromMe ? 'You: ' : ''}${last.content}`
            const time = new Date(last.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
            const isOpen = feedbackOpenFor === conv.other_user_id
            const form = getFormState(conv.other_user_id)

            return (
              <div key={conv.other_user_id} style={{ marginBottom: '10px' }}>
                <div
                  onClick={() => navigate(`/chat/${conv.other_user_id}`)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '14px',
                    padding: '14px 16px',
                    borderRadius: 'var(--radius)',
                    cursor: 'pointer',
                    transition: 'background 0.15s',
                    background: 'var(--surface)',
                    border: '1px solid var(--border)',
                  }}
                  onMouseEnter={e => e.currentTarget.style.background = 'var(--surface2, rgba(255,255,255,0.05))'}
                  onMouseLeave={e => e.currentTarget.style.background = 'var(--surface)'}
                >
                  {other.photo_url ? (
                    <img
                      src={other.photo_url}
                      alt={other.name}
                      style={{ width: '46px', height: '46px', borderRadius: '50%', objectFit: 'cover', flexShrink: 0 }}
                    />
                  ) : (
                    <div style={{
                      width: '46px', height: '46px', borderRadius: '50%',
                      background: 'var(--border)', display: 'flex', alignItems: 'center',
                      justifyContent: 'center', fontSize: '18px', flexShrink: 0,
                    }}>
                      {other.name?.[0] || '?'}
                    </div>
                  )}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontWeight: 600, fontSize: '15px', marginBottom: '2px' }}>
                      {other.name}
                      {other.age && <span style={{ fontWeight: 400, color: 'var(--text2)', fontSize: '13px' }}> · {other.age}</span>}
                    </div>
                    <div style={{
                      fontSize: '13px', color: 'var(--text2)',
                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    }}>
                      {preview.length > 60 ? preview.slice(0, 60) + '…' : preview}
                    </div>
                  </div>
                  <div style={{ fontSize: '12px', color: 'var(--text2)', flexShrink: 0 }}>
                    {time}
                  </div>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 4px 0 4px' }}>
                  <button
                    className="btn-ghost"
                    onClick={() => setFeedbackOpenFor(isOpen ? null : conv.other_user_id)}
                    style={{ fontSize: '12px', padding: '4px 10px' }}
                  >
                    {isOpen ? 'Close meetup feedback' : 'Did you meet? Add feedback'}
                  </button>
                  {feedbackSuccess[conv.other_user_id] && (
                    <span style={{ fontSize: '12px', color: '#6cc48a' }}>{feedbackSuccess[conv.other_user_id]}</span>
                  )}
                </div>

                {isOpen && (
                  <div style={{
                    marginTop: '8px',
                    border: '1px solid var(--border)',
                    borderRadius: 'var(--radius)',
                    background: 'var(--surface)',
                    padding: '12px',
                    display: 'grid',
                    gap: '10px',
                  }}>
                    <label style={{ fontSize: '13px', color: 'var(--text2)' }}>
                      Did you two meet in person?
                      <select
                        value={form.met}
                        onChange={(e) => updateForm(conv.other_user_id, { met: e.target.value })}
                        style={{ marginTop: '6px' }}
                      >
                        <option value="yes">Yes</option>
                        <option value="no">No</option>
                      </select>
                    </label>

                    {form.met === 'yes' && (
                      <>
                        <label style={{ fontSize: '13px', color: 'var(--text2)' }}>
                          Chemistry (1-5)
                          <input
                            type="number"
                            min="1"
                            max="5"
                            value={form.chemistry_rating}
                            onChange={(e) => updateForm(conv.other_user_id, { chemistry_rating: e.target.value })}
                            style={{ marginTop: '6px' }}
                          />
                        </label>
                        <label style={{ fontSize: '13px', color: 'var(--text2)' }}>
                          Communication (1-5)
                          <input
                            type="number"
                            min="1"
                            max="5"
                            value={form.communication_rating}
                            onChange={(e) => updateForm(conv.other_user_id, { communication_rating: e.target.value })}
                            style={{ marginTop: '6px' }}
                          />
                        </label>
                        <label style={{ fontSize: '13px', color: 'var(--text2)' }}>
                          Safety/comfort (1-5)
                          <input
                            type="number"
                            min="1"
                            max="5"
                            value={form.safety_rating}
                            onChange={(e) => updateForm(conv.other_user_id, { safety_rating: e.target.value })}
                            style={{ marginTop: '6px' }}
                          />
                        </label>
                        <label style={{ fontSize: '13px', color: 'var(--text2)' }}>
                          Would you meet again?
                          <select
                            value={form.would_meet_again}
                            onChange={(e) => updateForm(conv.other_user_id, { would_meet_again: e.target.value })}
                            style={{ marginTop: '6px' }}
                          >
                            <option value="yes">Yes</option>
                            <option value="no">No</option>
                          </select>
                        </label>
                      </>
                    )}

                    <label style={{ fontSize: '13px', color: 'var(--text2)' }}>
                      Notes (optional)
                      <textarea
                        value={form.notes}
                        onChange={(e) => updateForm(conv.other_user_id, { notes: e.target.value })}
                        rows={3}
                        placeholder="Share what went well or what felt off"
                        style={{ marginTop: '6px', resize: 'vertical' }}
                      />
                    </label>

                    <div style={{ display: 'flex', gap: '8px' }}>
                      <button
                        className="btn-primary"
                        onClick={() => handleSubmitFeedback(conv.other_user_id)}
                        disabled={submittingFor === conv.other_user_id}
                      >
                        {submittingFor === conv.other_user_id ? 'Saving...' : 'Save feedback'}
                      </button>
                      <button className="btn-ghost" onClick={() => setFeedbackOpenFor(null)}>Cancel</button>
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
