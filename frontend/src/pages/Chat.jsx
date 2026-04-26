import { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { getUser, sendDM, getDMs, unmatch } from '../lib/api'

export default function Chat() {
  const { matchId } = useParams()
  const navigate = useNavigate()
  const [match, setMatch] = useState(null)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [unmatching, setUnmatching] = useState(false)
  const [confirmUnmatch, setConfirmUnmatch] = useState(false)
  const messagesEndRef = useRef(null)
  const pollRef = useRef(null)

  const user = JSON.parse(localStorage.getItem('wavelength_user') || '{}')

  useEffect(() => {
    if (!user.user_id) {
      navigate('/onboard')
      return
    }
    if (!matchId) {
      navigate('/matches')
      return
    }

    const loadInitial = async () => {
      try {
        const [matchRes, dmsRes] = await Promise.all([
          getUser(matchId),
          getDMs(user.user_id, matchId)
        ])
        setMatch(matchRes.data)
        setMessages(dmsRes.data.messages || [])
      } catch (err) {
        setError('Failed to load conversation')
        console.error(err)
      } finally {
        setLoading(false)
      }
    }

    loadInitial()

    // Poll for new messages every 3s
    pollRef.current = setInterval(async () => {
      try {
        const res = await getDMs(user.user_id, matchId)
        setMessages(res.data.messages || [])
      } catch {}
    }, 3000)

    return () => clearInterval(pollRef.current)
  }, [matchId])

  const handleSend = async () => {
    const content = input.trim()
    if (!content || sending) return

    setSending(true)
    setInput('')
    setError('')

    try {
      const res = await sendDM({ from_user_id: user.user_id, to_user_id: matchId, content })
      setMessages(prev => [...prev, res.data])
    } catch (err) {
      setError('Failed to send message')
      setInput(content)
      console.error(err)
    } finally {
      setSending(false)
    }
  }

  const handleUnmatch = async () => {
    setUnmatching(true)
    try {
      await unmatch({ user_id_a: user.user_id, user_id_b: matchId })
      navigate('/messages')
    } catch (err) {
      setError('Failed to unmatch')
      setUnmatching(false)
    }
  }

  if (loading) {
    return <div style={{ padding: '60px 24px', textAlign: 'center' }}>Loading...</div>
  }

  return (
    <div className="chat-container">
      {/* Header */}
      <div style={{
        padding: '14px 24px',
        borderBottom: '1px solid var(--border)',
        display: 'flex',
        alignItems: 'center',
        gap: '12px',
      }}>
        <button
          className="btn-ghost"
          onClick={() => navigate('/matches')}
          style={{ fontSize: '13px', padding: '4px 10px' }}
        >
          ← Back
        </button>
        {match?.photo_url && (
          <img
            src={match.photo_url}
            alt={match.name}
            style={{ width: '36px', height: '36px', borderRadius: '50%', objectFit: 'cover' }}
          />
        )}
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 600, fontSize: '15px' }}>{match?.name}</div>
          {match?.age && (
            <div style={{ fontSize: '12px', color: 'var(--text2)' }}>
              {match.age}{match.gender ? ` · ${match.gender}` : ''}
            </div>
          )}
        </div>
        {!confirmUnmatch ? (
          <button
            className="btn-ghost"
            onClick={() => setConfirmUnmatch(true)}
            style={{ fontSize: '12px', color: 'var(--text2)', padding: '4px 10px' }}
          >
            Unmatch
          </button>
        ) : (
          <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
            <span style={{ fontSize: '12px', color: 'var(--text2)' }}>Are you sure?</span>
            <button
              className="btn-ghost"
              onClick={handleUnmatch}
              disabled={unmatching}
              style={{ fontSize: '12px', color: '#d4825a', padding: '4px 10px' }}
            >
              {unmatching ? 'Removing...' : 'Yes, unmatch'}
            </button>
            <button
              className="btn-ghost"
              onClick={() => setConfirmUnmatch(false)}
              style={{ fontSize: '12px', padding: '4px 10px' }}
            >
              Cancel
            </button>
          </div>
        )}
      </div>

      {/* Messages */}
      <div className="chat-messages">
        {error && (
          <div style={{
            background: 'rgba(212, 130, 90, 0.1)',
            border: '1px solid rgba(212, 130, 90, 0.3)',
            color: '#d4825a',
            padding: '12px',
            borderRadius: 'var(--radius)',
            alignSelf: 'center',
            maxWidth: '75%',
            fontSize: '14px'
          }}>
            {error}
          </div>
        )}

        {messages.length === 0 && !error && (
          <div style={{ alignSelf: 'center', color: 'var(--text2)', fontSize: '14px', marginTop: '32px' }}>
            Start the conversation with {match?.name || 'your match'}.
          </div>
        )}

        {messages.map((msg) => {
          const isMe = msg.from_user_id === user.user_id
          return (
            <div
              key={msg.id}
              className={`message ${isMe ? 'user' : 'assistant'}`}
            >
              {msg.content}
            </div>
          )
        })}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="chat-input-area">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSend()}
          placeholder={`Message ${match?.name || ''}...`}
          disabled={sending}
        />
        <button
          onClick={handleSend}
          disabled={sending || !input.trim()}
          className="btn-primary"
        >
          {sending ? '...' : 'Send'}
        </button>
      </div>
    </div>
  )
}
