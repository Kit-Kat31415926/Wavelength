import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { startInterview, sendMessage, sendMessageAudio, extractWavelengthlity, textToSpeech } from '../lib/api'
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
  useEffect(() => {
    voiceModeRef.current = voiceMode
    if (!voiceMode) {
      // Stop any in-flight TTS request and audio playback immediately
      if (ttsAbortRef.current) {
        ttsAbortRef.current.abort()
        ttsAbortRef.current = null
      }
      if (currentAudioRef.current) {
        currentAudioRef.current.pause()
        currentAudioRef.current.currentTime = 0
      }
      if (currentAudioUrlRef.current) {
        URL.revokeObjectURL(currentAudioUrlRef.current)
        currentAudioUrlRef.current = null
      }
    }
  }, [voiceMode])
  const [isListening, setIsListening] = useState(false)
  const [voiceSupported, setVoiceSupported] = useState(true)
  const [audioUnlocked, setAudioUnlocked] = useState(false)
  const [isRecording, setIsRecording] = useState(false)
  const [audioInsights, setAudioInsights] = useState(null)
  const [showAudioDebug, setShowAudioDebug] = useState(false)
  const messagesEndRef = useRef(null)
  const currentAudioRef = useRef(null)
  const currentAudioUrlRef = useRef(null)
  const recognitionRef = useRef(null)
  const generationAbortRef = useRef(null)
  const ttsAbortRef = useRef(null)
  const voiceModeRef = useRef(true)
  const submitUserMessageRef = useRef(null)
  const audioContextRef = useRef(null)
  const audioSourceRef = useRef(null)
  const audioProcessorRef = useRef(null)
  const audioGainRef = useRef(null)
  const audioStreamRef = useRef(null)
  const audioBufferRef = useRef([])
  const isRecordingRef = useRef(false)
  const audioSampleRateRef = useRef(44100)
  const accumulatedTranscriptRef = useRef('')  // builds up across continuous utterances
  const silenceTimerRef = useRef(null)         // auto-submits after 4s of silence

  const user = JSON.parse(localStorage.getItem('wavelength_user') || '{}')

  const mergeAudioBuffers = (buffers) => {
    const length = buffers.reduce((sum, buffer) => sum + buffer.length, 0)
    const result = new Float32Array(length)
    let offset = 0
    buffers.forEach((buffer) => {
      result.set(buffer, offset)
      offset += buffer.length
    })
    return result
  }

  const createWavBlob = () => {
    const samples = mergeAudioBuffers(audioBufferRef.current)
    const sampleRate = audioSampleRateRef.current
    const buffer = new ArrayBuffer(44 + samples.length * 2)
    const view = new DataView(buffer)

    const writeString = (viewArg, offset, string) => {
      for (let i = 0; i < string.length; i += 1) {
        viewArg.setUint8(offset + i, string.charCodeAt(i))
      }
    }

    const floatTo16BitPCM = (viewArg, offset, input) => {
      for (let i = 0; i < input.length; i += 1, offset += 2) {
        let s = Math.max(-1, Math.min(1, input[i]))
        s = s < 0 ? s * 0x8000 : s * 0x7fff
        viewArg.setInt16(offset, s, true)
      }
    }

    writeString(view, 0, 'RIFF')
    view.setUint32(4, 36 + samples.length * 2, true)
    writeString(view, 8, 'WAVE')
    writeString(view, 12, 'fmt ')
    view.setUint32(16, 16, true)
    view.setUint16(20, 1, true)
    view.setUint16(22, 1, true)
    view.setUint32(24, sampleRate, true)
    view.setUint32(28, sampleRate * 2, true)
    view.setUint16(32, 2, true)
    view.setUint16(34, 16, true)
    writeString(view, 36, 'data')
    view.setUint32(40, samples.length * 2, true)
    floatTo16BitPCM(view, 44, samples)

    return new Blob([view], { type: 'audio/wav' })
  }

  const stopAudioCapture = async () => {
    if (!isRecordingRef.current) {
      console.log('stopAudioCapture: not currently recording')
      return null
    }
    console.log('stopAudioCapture: stopping recording')
    isRecordingRef.current = false
    setIsRecording(false)

    if (audioProcessorRef.current) {
      audioProcessorRef.current.disconnect()
      audioProcessorRef.current = null
    }
    if (audioGainRef.current) {
      audioGainRef.current.disconnect()
      audioGainRef.current = null
    }
    if (audioSourceRef.current) {
      audioSourceRef.current.disconnect()
      audioSourceRef.current = null
    }
    if (audioContextRef.current) {
      try {
        await audioContextRef.current.close()
      } catch (err) {
        console.warn('AudioContext close failed', err)
      }
      audioContextRef.current = null
    }
    if (audioStreamRef.current) {
      audioStreamRef.current.getTracks().forEach((track) => track.stop())
      audioStreamRef.current = null
    }

    if (!audioBufferRef.current.length) {
      console.log('stopAudioCapture: no audio data captured')
      return null
    }

    const blob = createWavBlob()
    audioBufferRef.current = []
    console.log('stopAudioCapture: created blob of size', blob.size)
    return blob
  }

  const startAudioCapture = async () => {
    if (!navigator.mediaDevices?.getUserMedia) {
      setError('Audio recording is not supported in this browser.')
      return false
    }

    try {
      console.log('Requesting microphone access...')
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const audioContext = new AudioContext()
      const source = audioContext.createMediaStreamSource(stream)
      const processor = audioContext.createScriptProcessor(4096, 1, 1)

      audioBufferRef.current = []
      audioSampleRateRef.current = audioContext.sampleRate
      audioStreamRef.current = stream
      audioContextRef.current = audioContext
      audioSourceRef.current = source
      audioProcessorRef.current = processor

      processor.onaudioprocess = (event) => {
        if (!isRecordingRef.current) return
        const input = event.inputBuffer.getChannelData(0)
        audioBufferRef.current.push(new Float32Array(input))
      }

      const silentGain = audioContext.createGain()
      silentGain.gain.value = 0
      audioGainRef.current = silentGain

      source.connect(processor)
      processor.connect(silentGain)
      silentGain.connect(audioContext.destination)

      isRecordingRef.current = true
      setIsRecording(true)
      console.log('Audio capture started successfully')
      return true
    } catch (err) {
      console.error('Unable to initialize audio capture', err)
      setError('Unable to access microphone. Please allow mic access and try again.')
      return false
    }
  }

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
        if (generationController.signal.aborted) {
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
    recognition.continuous = true   // keep listening through thinking pauses
    recognition.maxAlternatives = 1

    // Only starts after first speech — not on button press, so thinking before
    // starting doesn't count. Resets every time a new utterance segment arrives.
    const SILENCE_TIMEOUT_MS = 7000

    const resetSilenceTimer = () => {
      if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current)
      silenceTimerRef.current = setTimeout(() => {
        recognitionRef.current?.stop()
      }, SILENCE_TIMEOUT_MS)
    }

    recognition.onstart = () => {
      accumulatedTranscriptRef.current = ''
      // Do NOT start the silence timer here — wait until speech actually arrives
    }

    recognition.onresult = (event) => {
      // Append each new final segment as the speaker produces it
      for (let i = event.resultIndex; i < event.results.length; i++) {
        if (event.results[i].isFinal) {
          accumulatedTranscriptRef.current += event.results[i][0].transcript + ' '
        }
      }
      // Start/reset the 7s silence timer only after real speech has been detected
      resetSilenceTimer()
    }

    recognition.onerror = (event) => {
      console.error('Speech recognition error:', event.error)
      if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current)
      setError(`Voice input error: ${event.error}`)
      setIsListening(false)
      stopAudioCapture()
    }

    recognition.onend = async () => {
      console.log('Speech recognition ended')
      if (silenceTimerRef.current) {
        clearTimeout(silenceTimerRef.current)
        silenceTimerRef.current = null
      }
      setIsListening(false)
      const transcript = accumulatedTranscriptRef.current.trim()
      accumulatedTranscriptRef.current = ''
      const audioBlob = await stopAudioCapture()
      if (transcript) {
        await submitUserMessageRef.current?.(transcript, audioBlob)
      }
    }

    recognitionRef.current = recognition

    return () => {
      if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current)
      if (recognitionRef.current) {
        recognitionRef.current.stop()
      }
      stopAudioCapture()
    }
  }, [])

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
    return voiceModeRef.current && onInterviewRoute && tabVisible
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

  const cancelSpeaking = () => {
    // Only cancel TTS and voice input, NOT generation requests
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
  }

  useEffect(() => {
    const handleVisibilityChange = () => {
      if (!isChatTabActive()) {
        cancelSpeaking()
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
      cancelSpeaking()
    }
  }, [location.pathname])

  const speakAssistant = async (text) => {
    if (!text?.trim()) return

    if (!isChatActiveForVoice()) {
      console.log('TTS skipped because chat is not active for voice', {
        voiceMode,
        pathname: location.pathname,
        visible: document.visibilityState,
      })
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
    cancelSpeaking()
    const lastAssistant = [...messages].reverse().find(m => m.role === 'assistant')
    if (!lastAssistant?.content) {
      setAudioUnlocked(true)
      return
    }
    await speakAssistant(lastAssistant.content)
  }

  const submitUserMessage = useCallback(async (rawMessage, audioBlob = null) => {
    const userMessage = (rawMessage || '').trim()
    if (!userMessage || isTyping || !sessionId || !canUserRespond) {
      return
    }

    console.log('submitUserMessage called with:', {
      userMessage: userMessage.substring(0, 50),
      sessionId,
      hasAudioBlob: !!audioBlob,
      voiceMode,
      isListening,
      isRecording
    })
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

      let res
      if (audioBlob) {
        console.log('Sending audio message, blob size:', audioBlob.size)
        const formData = new FormData()
        formData.append('session_id', sessionId)
        formData.append('message', userMessage)
        formData.append('audio_file', audioBlob, 'response.wav')

        res = await sendMessageAudio(formData, {
          signal: generationController.signal
        })
        console.log('Audio response received:', res.data)
      } else {
        console.log('Sending text message')
        res = await sendMessage(
          { session_id: sessionId, message: userMessage },
          { signal: generationController.signal
        })
      }

      if (generationController.signal.aborted || !isChatTabActive()) {
        console.log('Request aborted or tab inactive')
        return
      }

      setMessages(prev => [...prev, { role: 'assistant', content: res.data.message }])
      await speakAssistant(res.data.message)
      setTurn(res.data.turn)

      if (res.data.is_complete) {
        setIsComplete(true)
      }
      
      // Store audio insights if available
      if (res.data.audio_insights) {
        console.log('Audio insights received:', res.data.audio_insights)
        setAudioInsights(res.data.audio_insights)
      } else {
        console.log('No audio insights in response')
      }
    } catch (err) {
      if (err?.name === 'CanceledError' || err?.code === 'ERR_CANCELED') {
        console.log('Request was cancelled')
        return
      }
      console.error('submitUserMessage error:', err)
      if (err?.response) {
        console.error('submitUserMessage response data:', err.response.data)
        console.error('submitUserMessage response status:', err.response.status)
        if (err.response.status === 404 && err.response.data?.detail === 'Session not found') {
          setError('Session not found. Your interview session may have expired. Please restart the interview.')
          return
        }
      }
      setError('Failed to send message')
    } finally {
      generationAbortRef.current = null
      setIsTyping(false)
    }
  }, [sessionId, isTyping, canUserRespond, speakAssistant])

  const handleSendMessage = async () => {
    await submitUserMessage(input)
  }

  // Keep ref in sync with current submitUserMessage function
  useEffect(() => {
    submitUserMessageRef.current = submitUserMessage
  }, [submitUserMessage])

  const handleVoiceCapture = async () => {
    // Interrupt any audio that's currently playing
    if (currentAudioRef.current && !currentAudioRef.current.paused) {
      cancelSpeaking()
    }

    if (!recognitionRef.current) {
      setError('Voice input is not supported in this browser')
      return
    }

    if (isListening) {
      // Stopping manually — cancel the silence timer and let onend handle submit
      if (silenceTimerRef.current) {
        clearTimeout(silenceTimerRef.current)
        silenceTimerRef.current = null
      }
      recognitionRef.current.stop()
      return
    }

    setError('')
    const started = await startAudioCapture()
    if (!started) {
      return
    }

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
      const transcript = messages
        .filter(m => m?.role === 'user' || m?.role === 'assistant')
        .map(m => ({ role: m.role, content: m.content }))

      await extractWavelengthlity({
        session_id: sessionId,
        user_id: user.user_id,
        name: user.name,
        transcript,
      })
      navigate('/portrait')
    } catch (err) {
      const detail = err?.response?.data?.detail || ''
      if (detail.toLowerCase().includes('session not found')) {
        setError('Session expired after a server restart. Please send one more message, then try again.')
      } else {
        setError('Failed to extract profile')
      }
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
        {voiceMode && (
          <button
            className="btn-ghost"
            onClick={() => setShowAudioDebug(prev => !prev)}
            style={{ fontSize: '12px', padding: '4px 10px', marginLeft: '8px' }}
          >
            {showAudioDebug ? 'Hide Audio Debug' : 'Show Audio Debug'}
          </button>
        )}
      </div>

      {/* Voice status */}
      {voiceMode && (
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
            All assistant replies are spoken.
          </p>
          <p className="muted" style={{ marginTop: '12px', fontSize: '13px' }}>
            {!canUserRespond
              ? 'Connecting you with an agent...'
              : isTyping
                ? 'Assistant is thinking...'
                : isRecording
                  ? 'Recording audio...'
                  : isListening
                    ? 'Listening...'
                    : 'Tap Start speaking to respond.'}
          </p>
            {(audioUnlocked || [...messages].reverse().find(m => m.role === 'assistant')) && !isTyping && (
            <button
              className="btn-ghost"
              style={{ marginTop: '10px', fontSize: '12px', padding: '6px 10px' }}
              onClick={handleEnableSpeaker}
            >
              🔊 Replay last response
            </button>
          )}

          {audioInsights?.audio_personality?.primary_style && (
            <div style={{ marginTop: '12px', fontSize: '13px', color: 'var(--text2)' }}>
              Last audio style: {audioInsights.audio_personality.primary_style}
              {audioInsights.audio_personality.secondary_style ? ` / ${audioInsights.audio_personality.secondary_style}` : ''}
            </div>
          )}
          {isTyping && (
            <div style={{ marginTop: '12px', display: 'flex', justifyContent: 'center' }}>
              <TypingIndicator />
            </div>
          )}
        </div>
      )}
      
      {/* Error Messages */}
      {error && error.toLowerCase().includes('blocked') && (
        <div style={{
          background: 'rgba(255, 193, 7, 0.15)',
          border: '1px solid rgba(255, 193, 7, 0.4)',
          color: '#ffc107',
          padding: '12px 24px',
          borderRadius: 'var(--radius)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          alignSelf: 'center',
          maxWidth: '85%',
          fontSize: '14px',
          margin: '12px 0'
        }}>
          <span>🔇 Browser blocked audio. Tap to enable.</span>
          <button
            className="btn-ghost"
            style={{ fontSize: '12px', padding: '4px 8px', marginLeft: '12px', whiteSpace: 'nowrap' }}
            onClick={handleEnableSpeaker}
          >
            Enable →
          </button>
        </div>
      )}

      {error && !error.toLowerCase().includes('blocked') && (
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

      {messages
        .filter(msg => !voiceMode)
        .map((msg, idx) => (
          <div key={idx} className={`message ${msg.role}`}>
            {msg.content}
          </div>
      ))}

      {isTyping && !voiceMode && (
        <div className="message assistant">
          <TypingIndicator />
        </div>
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

      {/* Audio Debug Panel */}
      {showAudioDebug && (
        <div style={{
          padding: '16px',
          margin: '16px 24px',
          background: 'var(--bg2)',
          borderRadius: 'var(--radius)',
          border: '1px solid var(--border)',
          fontSize: '12px',
          fontFamily: 'monospace'
        }}>
          <div style={{ fontWeight: 'bold', marginBottom: '10px', color: 'var(--text2)' }}>
            🎤 Last Audio Analysis
          </div>
          {audioInsights ? (() => {
            const ap = audioInsights.audio_personality || {}
            const ts = audioInsights.transcript_signals || {}
            const fillerPct = ts.filler_rate != null ? (ts.filler_rate * 100).toFixed(1) + '%' : null
            const voicedPct = audioInsights.voiced_ratio != null ? Math.round(audioInsights.voiced_ratio * 100) + '%' : null
            const wpm = (ts.word_count && audioInsights.duration_seconds)
              ? Math.round(ts.word_count / (audioInsights.duration_seconds / 60))
              : null
            const pitchHz = audioInsights.pitch_median_hz > 0 ? Math.round(audioInsights.pitch_median_hz) + ' Hz' : null
            const expressiveness = ap.heuristic?.expressiveness || audioInsights.expressiveness
            return (
              <div>
                {/* Row 1: raw audio stats */}
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '6px', marginBottom: '10px' }}>
                  <div><span style={{ color: 'var(--text3)' }}>duration</span><br />{audioInsights.duration_seconds}s</div>
                  <div><span style={{ color: 'var(--text3)' }}>volume</span><br />{audioInsights.approx_db} dB</div>
                  <div><span style={{ color: 'var(--text3)' }}>voice activity</span><br />{voicedPct ?? '—'}</div>
                </div>
                {/* Row 2: behavioral signals */}
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '6px', marginBottom: '10px' }}>
                  {wpm != null && <div><span style={{ color: 'var(--text3)' }}>pace</span><br />{wpm} wpm</div>}
                  <div>
                    <span style={{ color: 'var(--text3)' }}>thinking pauses</span><br />
                    {audioInsights.pause_count ?? 0}× avg {audioInsights.avg_pause_sec?.toFixed(1) ?? '0'}s
                  </div>
                  {expressiveness && <div><span style={{ color: 'var(--text3)' }}>energy</span><br />{expressiveness.replace(/_/g, ' ')}</div>}
                  {pitchHz && <div><span style={{ color: 'var(--text3)' }}>pitch</span><br />{pitchHz}</div>}
                  {fillerPct != null && <div><span style={{ color: 'var(--text3)' }}>fillers</span><br />{fillerPct} of words</div>}
                </div>
                {/* Row 3: computed labels */}
                {(ap.emotion_state || ap.articulation_level || ap.talk_style || ap.primary_style) && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                    {ap.emotion_state && <span style={{ background: 'var(--bg3)', padding: '2px 8px', borderRadius: '4px', color: 'var(--accent)' }}>{ap.emotion_state}</span>}
                    {ap.articulation_level && <span style={{ background: 'var(--bg3)', padding: '2px 8px', borderRadius: '4px' }}>{ap.articulation_level}</span>}
                    {ap.talk_style && <span style={{ background: 'var(--bg3)', padding: '2px 8px', borderRadius: '4px' }}>{ap.talk_style}</span>}
                    {ap.primary_style && <span style={{ background: 'var(--bg3)', padding: '2px 8px', borderRadius: '4px' }}>{ap.primary_style}</span>}
                    {ap.source && <span style={{ color: 'var(--text3)', padding: '2px 8px' }}>via {ap.source}</span>}
                  </div>
                )}
                {ap.compatibility_insight && (
                  <div style={{ marginTop: '10px', color: 'var(--text2)', lineHeight: 1.4, fontSize: '11px' }}>
                    {ap.compatibility_insight}
                  </div>
                )}
              </div>
            )
          })() : (
            <div style={{ color: 'var(--text3)' }}>
              Waiting for first audio response...
            </div>
          )}
        </div>
      )}

      {/* Input */}
      {!isComplete && (
        <div className="chat-input-area">
          {voiceMode ? (
            <>
              {canUserRespond && !isTyping && (
                <button
                  onClick={handleVoiceCapture}
                  disabled={isTyping || !voiceSupported || !canUserRespond}
                  className="btn-primary"
                >
                  {isRecording ? 'Stop recording' : isListening ? 'Stop listening' : 'Start speaking'}
                </button>
              )}
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
