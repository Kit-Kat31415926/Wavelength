import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { aiChat } from '../lib/api'
import TypingIndicator from '../components/TypingIndicator'

export default function AIChat() {
  const navigate = useNavigate()
  const [messages, setMessages] = useState([
    { role: 'assistant', content: "Hey! I'm your Wavelength AI companion. What's on your mind?" }
  ])
  const [input, setInput] = useState('')
  const [isTyping, setIsTyping] = useState(false)
  const [sessionId, setSessionId] = useState(null)
  const [error, setError] = useState('')
  const messagesEndRef = useRef(null)

  const user = JSON.parse(localStorage.getItem('wavelength_user') || '{}')

  useEffect(() => {
    if (!user.user_id) {
      navigate('/auth')
    }
  }, [])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isTyping])

  const sendMessage = async () => {
    const text = input.trim()
    if (!text || isTyping) return

    setInput('')
    setMessages(prev => [...prev, { role: 'user', content: text }])
    setIsTyping(true)
    setError('')

    try {
      const res = await aiChat({ session_id: sessionId, message: text })
      setSessionId(res.data.session_id)
      setMessages(prev => [...prev, { role: 'assistant', content: res.data.message }])
    } catch (err) {
      setError('Could not reach the AI. Please try again.')
      console.error(err)
    } finally {
      setIsTyping(false)
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  return (
    <div className="chat-container">
      <div style={{ padding: '16px 24px', borderBottom: '1px solid var(--border)' }}>
        <h2 style={{ fontFamily: 'var(--font-display)', color: 'var(--gold)', fontSize: '18px' }}>
          AI Companion
        </h2>
        <p style={{ color: 'var(--text2)', fontSize: '13px', marginTop: '2px' }}>
          Chat freely — no interview, just a conversation.
        </p>
      </div>

      <div className="chat-messages" style={{ flex: 1, overflowY: 'auto', padding: '24px 16px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
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

        {messages.map((msg, i) => (
          <div
            key={i}
            style={{
              alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start',
              maxWidth: '75%',
              background: msg.role === 'user' ? 'var(--surface)' : 'var(--bg2)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-lg)',
              padding: '12px 16px',
              color: msg.role === 'user' ? 'var(--text)' : 'var(--gold2)',
              fontSize: '15px',
              lineHeight: '1.5',
            }}
          >
            {msg.content}
          </div>
        ))}

        {isTyping && (
          <div style={{ alignSelf: 'flex-start' }}>
            <TypingIndicator />
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <div className="chat-input-bar">
        <input
          className="chat-input"
          type="text"
          placeholder="Type a message..."
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={isTyping}
        />
        <button
          className="btn-primary"
          onClick={sendMessage}
          disabled={!input.trim() || isTyping}
        >
          Send
        </button>
      </div>
    </div>
  )
}
