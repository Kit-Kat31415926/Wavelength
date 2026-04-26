import { useState, useEffect, useRef } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { startInterview, sendMessage, extractWavelengthlity, textToSpeech } from '../lib/api'
import TypingIndicator from '../components/TypingIndicator'

export default function Conversation() {
  const navigate = useNavigate()
  const location = useLocation()
  const [messages, setMessages] = useState([])
  const [sessionId, setSessionId] = useState(null)
  const [input, setInput] = useState('')
  const [isTyping, setIsTyping] = useState(false)
  const [isComplete, setIsComplete] = useState(false)
  const [isExtracting, setIsExtracting] = useState(false)
  const [error, setError] = useState('')
  const [turn, setTurn] = useState(0)
  const [canUserRespond, setCanUserRespond] = useState(false)
  const [voiceMode, setVoiceMode] = useState(true)
  const [isListening, setIsListening] = useState(false)
  const [voiceSupported, setVoiceSupported] = useState(true)
  const [audioUnlocked, setAudioUnlocked] = useState(false)
  const messagesEndRef = useRef(null)
  const currentAudioRef = useRef(null)
  const currentAudioUrlRef = useRef(null)
  const recognitionRef = useRef(null)
  const generationAbortRef = useRef(null)
  const ttsAbortRef = useRef(null)

  const user = JSON.parse(localStorage.getItem('wavelength_user') || '{}')

  useEffect(() => {
    if (!user.user_id || !user.profile_complete) {
      navigate('/onboard')
      return
    }

    const initInterview = async () => {
      try {
        if (generationAbortRef.current) {
          generationAbortRef.current.abort()
        }
        const generationController = new AbortController()
        generationAbortRef.current = generationController

        const res = await startInterview(
          { user_id: user.user_id, name: user.name },
          { signal: generationController.signal }
        )
        if (generationController.signal.aborted || !isChatTabActive()) {
          return
        }

        setSessionId(res.data.session_id)
        setMessages([{ role: 'assistant', content: res.data.message }])
        await speakAssistant(res.data.message)
        setCanUserRespond(true)
      } catch (err) {
        if (err?.name === 'CanceledError' || err?.code === 'ERR_CANCELED') {
          return
        }
        setError('Failed to start interview')
        console.error(err)
      } finally {
        generationAbortRef.current = null
      }
    }

    initInterview()
  }, [])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  useEffect(() => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SpeechRecognition) {
      setVoiceSupported(false)
      setVoiceMode(false)
      return
    }

    const recognition = new SpeechRecognition()
    recognition.lang = 'en-US'
    recognition.interimResults = false
    recognition.continuous = false
    recognition.maxAlternatives = 1

    recognition.onresult = async (event) => {
      const transcript = event.results?.[0]?.[0]?.transcript?.trim() || ''
      if (transcript) {
        await submitUserMessage(transcript)
      }
    }

    recognition.onerror = (event) => {
      setError(`Voice input error: ${event.error}`)
      setIsListening(false)
    }

    recognition.onend = () => {
      setIsListening(false)
    }

    recognitionRef.current = recognition

    return () => {
      if (recognitionRef.current) {
        recognitionRef.current.stop()
      }
    }
  }, [sessionId, isTyping])

  useEffect(() => {
    return () => {
      if (generationAbortRef.current) {
        generationAbortRef.current.abort()
      }
      if (ttsAbortRef.current) {
        ttsAbortRef.current.abort()
      }
      if (currentAudioRef.current) {
        currentAudioRef.current.pause()
      }
      if (currentAudioUrlRef.current) {
        URL.revokeObjectURL(currentAudioUrlRef.current)
      }
    }
  }, [])

  const isChatTabActive = () => {
    const onInterviewRoute = location.pathname === '/converse'
    const tabVisible = document.visibilityState === 'visible'
    return onInterviewRoute && tabVisible
  }

  const isChatActiveForVoice = () => {
    const onInterviewRoute = location.pathname === '/converse'
    const tabVisible = document.visibilityState === 'visible'
    return voiceMode && onInterviewRoute && tabVisible
  }

  const cancelAssistantWork = () => {
    if (generationAbortRef.current) {
      generationAbortRef.current.abort()
      generationAbortRef.current = null
    }
    if (ttsAbortRef.current) {
      ttsAbortRef.current.abort()
      ttsAbortRef.current = null
    }
    if (currentAudioRef.current) {
      currentAudioRef.current.pause()
      currentAudioRef.current.currentTime = 0
    }
    if (isListening && recognitionRef.current) {
      recognitionRef.current.stop()
    }
    setIsTyping(false)
  }

  useEffect(() => {
    const handleVisibilityChange = () => {
      if (!isChatTabActive()) {
        cancelAssistantWork()
      }
    }

    handleVisibilityChange()
    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [voiceMode, location.pathname, isListening])

  useEffect(() => {
    if (!isChatTabActive()) {
      cancelAssistantWork()
    }
  }, [location.pathname])

  const speakAssistant = async (text) => {
    if (!text?.trim()) return

    if (!isChatActiveForVoice()) {
      return false
    }

    try {
      if (ttsAbortRef.current) {
        ttsAbortRef.current.abort()
      }
      const ttsController = new AbortController()
      ttsAbortRef.current = ttsController

      const res = await textToSpeech({ text }, { signal: ttsController.signal })
      if (ttsController.signal.aborted || !isChatActiveForVoice()) {
        return false
      }

      const contentType = res?.headers?.['content-type'] || ''
      if (!contentType.includes('audio')) {
        const errorText = await res.data.text()
        let detail = 'TTS request failed'
        try {
          detail = JSON.parse(errorText)?.detail || detail
        } catch {
          detail = errorText || detail
        }
        throw new Error(detail)
      }
      const audioUrl = URL.createObjectURL(res.data)

      if (currentAudioRef.current) {
        currentAudioRef.current.pause()
      }
      if (currentAudioUrlRef.current) {
        URL.revokeObjectURL(currentAudioUrlRef.current)
      }

      const audio = new Audio(audioUrl)
      currentAudioRef.current = audio
      currentAudioUrlRef.current = audioUrl
      await audio.play()
      setAudioUnlocked(true)
      setError('')
      return true
    } catch (err) {
      if (err?.name === 'CanceledError' || err?.code === 'ERR_CANCELED') {
        return false
      }
      const errMsg = String(err?.message || '')
      if (errMsg.toLowerCase().includes('notallowederror')) {
        setError('Audio is blocked by browser autoplay. Tap "Enable speaker" once, then audio will play.')
      } else {
        setError(`Voice playback unavailable: ${errMsg || 'Unknown error'}`)
      }
      console.error('TTS playback unavailable:', err)
      return false
    }
  }

  const handleEnableSpeaker = async () => {
    const lastAssistant = [...messages].reverse().find(m => m.role === 'assistant')
    if (!lastAssistant?.content) {
      setAudioUnlocked(true)
      return
    }
    await speakAssistant(lastAssistant.content)
  }

  const submitUserMessage = async (rawMessage) => {
    const userMessage = (rawMessage || '').trim()
    if (!userMessage || isTyping || !sessionId || !canUserRespond) return

    setInput('')
    setMessages(prev => [...prev, { role: 'user', content: userMessage }])
    setIsTyping(true)
    setError('')

    try {
      if (generationAbortRef.current) {
        generationAbortRef.current.abort()
      }
      const generationController = new AbortController()
      generationAbortRef.current = generationController

      const res = await sendMessage(
        { session_id: sessionId, message: userMessage },
        { signal: generationController.signal }
      )
      if (generationController.signal.aborted || !isChatTabActive()) {
        return
      }

      setMessages(prev => [...prev, { role: 'assistant', content: res.data.message }])
      await speakAssistant(res.data.message)
      setTurn(res.data.turn)

      if (res.data.is_complete) {
        setIsComplete(true)
      }
    } catch (err) {
      if (err?.name === 'CanceledError' || err?.code === 'ERR_CANCELED') {
        return
      }
      setError('Failed to send message')
      console.error(err)
    } finally {
      generationAbortRef.current = null
      setIsTyping(false)
    }
  }

  const handleSendMessage = async () => {
    await submitUserMessage(input)
  }

  const handleVoiceCapture = () => {
    if (!recognitionRef.current) {
      setError('Voice input is not supported in this browser')
      return
    }

    if (isListening) {
      recognitionRef.current.stop()
      setIsListening(false)
      return
    }

    setError('')
    try {
      recognitionRef.current.start()
      setIsListening(true)
    } catch (err) {
      setError('Unable to start microphone. Please allow mic access and try again.')
      setIsListening(false)
      console.error(err)
    }
  }

  const handleExtractProfile = async () => {
    if (!sessionId || !user.user_id) return

    setIsExtracting(true)
    setMessages(prev => [...prev, { role: 'assistant', content: 'Analyzing your conversation...' }])

    try {
      await extractWavelengthlity({ session_id: sessionId, user_id: user.user_id })
      navigate('/portrait')
    } catch (err) {
      setError('Failed to extract profile')
      console.error(err)
      setIsExtracting(false)
      setMessages(prev => prev.slice(0, -1))
    }
  }

  return (
    <div className="chat-container">
      <div style={{ padding: '12px 24px', display: 'flex', justifyContent: 'flex-end' }}>
        <button
          className="btn-ghost"
          onClick={() => setVoiceMode(prev => !prev)}
          style={{ fontSize: '12px', padding: '4px 10px' }}
        >
          {voiceMode ? 'Voice mode: ON' : 'Voice mode: OFF'}
        </button>
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

        {voiceMode ? (
          <div style={{
            alignSelf: 'center',
            textAlign: 'center',
            marginTop: '24px',
            padding: '24px',
            background: 'var(--bg2)',
            borderRadius: 'var(--radius-lg)',
            border: '1px solid var(--border)',
            width: '100%',
            maxWidth: '560px'
          }}>
            <p style={{ marginBottom: '8px' }}>Voice mode is active.</p>
            <p className="muted" style={{ fontSize: '14px' }}>
              Assistant replies are spoken and hidden from text view.
            </p>
            <p className="muted" style={{ marginTop: '12px', fontSize: '13px' }}>
              {!canUserRespond
                ? 'Please wait for the opening message to finish...'
                : isTyping
                  ? 'Assistant is thinking...'
                  : isListening
                    ? 'Listening...'
                    : 'Tap Start speaking to respond.'}
            </p>
            <button
              className="btn-ghost"
              style={{ marginTop: '10px', fontSize: '12px', padding: '6px 10px' }}
              onClick={handleEnableSpeaker}
            >
              {audioUnlocked ? 'Replay last voice response' : 'Enable speaker'}
            </button>
            {isTyping && (
              <div style={{ marginTop: '12px', display: 'flex', justifyContent: 'center' }}>
                <TypingIndicator />
              </div>
            )}
          </div>
        ) : (
          <>
            {messages.map((msg, idx) => (
              <div key={idx} className={`message ${msg.role}`}>
                {msg.content}
              </div>
            ))}

            {isTyping && (
              <div className="message assistant">
                <TypingIndicator />
              </div>
            )}
          </>
        )}

        {isComplete && !isExtracting && (
          <div style={{
            alignSelf: 'center',
            textAlign: 'center',
            marginTop: '24px',
            padding: '24px',
            background: 'var(--bg2)',
            borderRadius: 'var(--radius-lg)',
            border: '1px solid var(--border)'
          }}>
            <p style={{ marginBottom: '16px', color: 'var(--text2)' }}>
              Your portrait is ready.
            </p>
            <button className="btn-primary" onClick={handleExtractProfile}>
              Generate Profile →
            </button>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      {!isComplete && (
        <div className="chat-input-area">
          {voiceMode ? (
            <>
              <button
                onClick={handleVoiceCapture}
                disabled={isTyping || !voiceSupported || !canUserRespond}
                className="btn-primary"
              >
                {isListening ? 'Stop listening' : 'Start speaking'}
              </button>
              {!voiceSupported && (
                <span className="muted" style={{ fontSize: '13px' }}>
                  Voice input not supported in this browser.
                </span>
              )}
            </>
          ) : (
            <>
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyPress={(e) => e.key === 'Enter' && handleSendMessage()}
                placeholder="Type your response..."
                disabled={isTyping || !canUserRespond}
              />
              <button
                onClick={handleSendMessage}
                disabled={isTyping || !input.trim() || !canUserRespond}
                className="btn-primary"
              >
                Send
              </button>
            </>
          )}
        </div>
      )}
    </div>
  )
}
