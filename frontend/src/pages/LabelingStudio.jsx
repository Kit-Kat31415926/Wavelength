import { useState, useEffect, useRef } from 'react'

const EMOTION_OPTIONS = ['hesitant', 'measured', 'low-energy', 'neutral', 'enthusiastic', 'elated']
const ARTICULATION_OPTIONS = ['hesitant', 'measured', 'deliberate', 'expressive', 'articulate']
const TALK_STYLE_OPTIONS = ['storyteller', 'deep-listener', 'quick-wit', 'earnest', 'conversational']
const FILLER_OPTIONS = ['none', 'low', 'moderate', 'high']

function SampleCard({ sample, localEdits, onEditChange, onSave, saveStatus }) {
  const isLabeled = !!sample.human_labels || saveStatus === 'saved'
  const savedLabels = saveStatus === 'saved' ? localEdits : sample.human_labels

  const getValue = (field) => {
    if (localEdits && localEdits[field] !== undefined) return localEdits[field]
    if (sample.human_labels) return sample.human_labels[field] || ''
    return ''
  }

  const handleChange = (field, value) => {
    onEditChange(sample.id, { ...(localEdits || {}), [field]: value })
  }

  return (
    <div style={{
      background: 'var(--bg2)',
      border: `1px solid ${isLabeled ? '#4caf50' : 'var(--border)'}`,
      borderRadius: 'var(--radius)',
      padding: '16px',
      marginBottom: '12px',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
        <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '13px', color: 'var(--gold)' }}>
            Turn {sample.turn}
          </span>
          <span className="muted" style={{ fontSize: '12px', fontFamily: 'var(--font-mono)' }}>
            {sample.session_id.slice(0, 8)}
          </span>
        </div>
        {isLabeled && (
          <span style={{ color: '#4caf50', fontSize: '13px', fontFamily: 'var(--font-mono)' }}>
            ✓ labeled
          </span>
        )}
      </div>

      <audio
        controls
        src={`http://localhost:8000${sample.audio_url}`}
        style={{ width: '100%', marginBottom: '14px', accentColor: 'var(--gold)' }}
      />

      <div style={{ marginBottom: '14px' }}>
        <div style={{
          fontSize: '11px',
          fontFamily: 'var(--font-mono)',
          color: 'var(--text3)',
          textTransform: 'uppercase',
          letterSpacing: '1px',
          marginBottom: '8px',
        }}>
          Auto-detected
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
          {sample.auto_labels && Object.entries(sample.auto_labels).map(([key, val]) => (
            <span key={key} className="tag" style={{ color: 'var(--text3)', borderColor: 'var(--border)' }}>
              {key.replace(/_/g, ' ')}: {val}
            </span>
          ))}
        </div>
      </div>

      <div style={{ marginBottom: '14px' }}>
        <div style={{
          fontSize: '11px',
          fontFamily: 'var(--font-mono)',
          color: 'var(--text3)',
          textTransform: 'uppercase',
          letterSpacing: '1px',
          marginBottom: '10px',
        }}>
          Human labels
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
          <label style={{ display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '13px', color: 'var(--text2)' }}>
            Emotion state
            <select
              value={getValue('emotion_state')}
              onChange={e => handleChange('emotion_state', e.target.value)}
              style={selectStyle}
            >
              <option value="">— select —</option>
              {EMOTION_OPTIONS.map(o => <option key={o} value={o}>{o}</option>)}
            </select>
          </label>

          <label style={{ display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '13px', color: 'var(--text2)' }}>
            Articulation level
            <select
              value={getValue('articulation_level')}
              onChange={e => handleChange('articulation_level', e.target.value)}
              style={selectStyle}
            >
              <option value="">— select —</option>
              {ARTICULATION_OPTIONS.map(o => <option key={o} value={o}>{o}</option>)}
            </select>
          </label>

          <label style={{ display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '13px', color: 'var(--text2)' }}>
            Talk style
            <select
              value={getValue('talk_style')}
              onChange={e => handleChange('talk_style', e.target.value)}
              style={selectStyle}
            >
              <option value="">— select —</option>
              {TALK_STYLE_OPTIONS.map(o => <option key={o} value={o}>{o}</option>)}
            </select>
          </label>

          <label style={{ display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '13px', color: 'var(--text2)' }}>
            Filler presence
            <select
              value={getValue('filler_presence')}
              onChange={e => handleChange('filler_presence', e.target.value)}
              style={selectStyle}
            >
              <option value="">— select —</option>
              {FILLER_OPTIONS.map(o => <option key={o} value={o}>{o}</option>)}
            </select>
          </label>
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        <button
          className="btn-primary"
          onClick={() => onSave(sample)}
          disabled={saveStatus === 'saving'}
          style={{ fontSize: '13px', padding: '8px 20px' }}
        >
          {saveStatus === 'saving' ? 'Saving...' : 'Save labels'}
        </button>
        {saveStatus === 'error' && (
          <span style={{ color: 'var(--warm)', fontSize: '13px' }}>Save failed — try again</span>
        )}
      </div>
    </div>
  )
}

const selectStyle = {
  background: 'var(--bg3)',
  border: '1px solid var(--border)',
  borderRadius: 'var(--radius)',
  color: 'var(--text)',
  padding: '6px 10px',
  fontFamily: 'var(--font-body)',
  fontSize: '13px',
  width: '100%',
}

function createWavBlob(buffers, sampleRate) {
  const total = buffers.reduce((s, b) => s + b.length, 0)
  const pcm = new Float32Array(total)
  let offset = 0
  buffers.forEach(b => { pcm.set(b, offset); offset += b.length })
  const buf = new ArrayBuffer(44 + pcm.length * 2)
  const view = new DataView(buf)
  const ws = (o, s) => { for (let i = 0; i < s.length; i++) view.setUint8(o + i, s.charCodeAt(i)) }
  ws(0, 'RIFF'); view.setUint32(4, 36 + pcm.length * 2, true); ws(8, 'WAVE'); ws(12, 'fmt ')
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true)
  view.setUint32(24, sampleRate, true); view.setUint32(28, sampleRate * 2, true)
  view.setUint16(32, 2, true); view.setUint16(34, 16, true); ws(36, 'data')
  view.setUint32(40, pcm.length * 2, true)
  for (let i = 0, o = 44; i < pcm.length; i++, o += 2) {
    const s = Math.max(-1, Math.min(1, pcm[i]))
    view.setInt16(o, s < 0 ? s * 0x8000 : s * 0x7fff, true)
  }
  return new Blob([view], { type: 'audio/wav' })
}

function BaselineRecorder({ onSampleAdded }) {
  const [recState, setRecState] = useState('idle') // idle | recording | uploading | done | error
  const ctxRef = useRef(null)
  const procRef = useRef(null)
  const srcRef = useRef(null)
  const gainRef = useRef(null)
  const streamRef = useRef(null)
  const buffersRef = useRef([])
  const srRef = useRef(44100)
  const isRecRef = useRef(false)

  const start = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const ctx = new AudioContext()
      const src = ctx.createMediaStreamSource(stream)
      const proc = ctx.createScriptProcessor(4096, 1, 1)
      const gain = ctx.createGain(); gain.gain.value = 0
      buffersRef.current = []; srRef.current = ctx.sampleRate
      proc.onaudioprocess = e => { if (isRecRef.current) buffersRef.current.push(new Float32Array(e.inputBuffer.getChannelData(0))) }
      src.connect(proc); proc.connect(gain); gain.connect(ctx.destination)
      ctxRef.current = ctx; procRef.current = proc; srcRef.current = src; gainRef.current = gain; streamRef.current = stream
      isRecRef.current = true
      setRecState('recording')
    } catch {
      setRecState('error')
    }
  }

  const stopAndUpload = async () => {
    isRecRef.current = false
    ;[procRef, gainRef, srcRef].forEach(r => { r.current?.disconnect(); r.current = null })
    try { await ctxRef.current?.close() } catch {}
    ctxRef.current = null
    streamRef.current?.getTracks().forEach(t => t.stop()); streamRef.current = null
    if (!buffersRef.current.length) { setRecState('error'); return }
    const blob = createWavBlob(buffersRef.current, srRef.current)
    buffersRef.current = []
    setRecState('uploading')
    try {
      const fd = new FormData(); fd.append('audio_file', blob, 'sample.wav')
      const res = await fetch('http://localhost:8000/audio/samples/upload', { method: 'POST', body: fd })
      if (!res.ok) throw new Error()
      const sample = await res.json()
      onSampleAdded(sample)
      setRecState('done')
      setTimeout(() => setRecState('idle'), 2000)
    } catch {
      setRecState('error')
      setTimeout(() => setRecState('idle'), 2000)
    }
  }

  return (
    <div style={{
      background: 'var(--bg2)',
      border: '1px solid var(--border)',
      borderRadius: 'var(--radius)',
      padding: '20px',
      marginBottom: '28px',
    }}>
      <div style={{ fontSize: '15px', fontWeight: 600, marginBottom: '6px' }}>Record a baseline sample</div>
      <p className="muted" style={{ fontSize: '13px', marginBottom: '16px' }}>
        Speak naturally for 5–15 seconds in whatever style you want to capture, then stop. The clip uploads immediately and appears in the list below.
      </p>
      <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
        <button
          className={recState === 'recording' ? 'btn-primary' : 'btn-ghost'}
          onClick={recState === 'recording' ? stopAndUpload : start}
          disabled={recState === 'uploading'}
          style={{ fontSize: '13px', padding: '8px 20px' }}
        >
          {recState === 'recording' ? '⏹ Stop & upload' : '⏺ Start recording'}
        </button>
        {recState === 'recording' && <span style={{ color: 'var(--warm)', fontSize: '13px' }}>Recording…</span>}
        {recState === 'uploading' && <span className="muted" style={{ fontSize: '13px' }}>Uploading…</span>}
        {recState === 'done' && <span style={{ color: '#4caf50', fontSize: '13px' }}>✓ Added to list</span>}
        {recState === 'error' && <span style={{ color: 'var(--warm)', fontSize: '13px' }}>Something went wrong</span>}
      </div>
    </div>
  )
}

export default function LabelingStudio() {
  const [samples, setSamples] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [filter, setFilter] = useState('unlabeled')
  const [edits, setEdits] = useState({})
  const [saveStatuses, setSaveStatuses] = useState({})

  useEffect(() => {
    fetch('http://localhost:8000/audio/samples')
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then(data => setSamples(data))
      .catch(err => setError(err.message || 'Failed to load samples'))
      .finally(() => setLoading(false))
  }, [])

  const handleEditChange = (id, fields) => {
    setEdits(prev => ({ ...prev, [id]: fields }))
  }

  const handleSave = async (sample) => {
    const id = sample.id
    setSaveStatuses(prev => ({ ...prev, [id]: 'saving' }))

    const humanLabels = edits[id] || sample.human_labels || {}

    try {
      const res = await fetch('http://localhost:8000/audio/label', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sample.session_id,
          turn: sample.turn,
          human_labels: {
            emotion_state: humanLabels.emotion_state || '',
            articulation_level: humanLabels.articulation_level || '',
            talk_style: humanLabels.talk_style || '',
            filler_presence: humanLabels.filler_presence || '',
          },
        }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setSamples(prev =>
        prev.map(s => s.id === id ? { ...s, human_labels: humanLabels } : s)
      )
      setSaveStatuses(prev => ({ ...prev, [id]: 'saved' }))
    } catch (err) {
      setSaveStatuses(prev => ({ ...prev, [id]: 'error' }))
    }
  }

  const handleSampleAdded = (sample) => {
    setSamples(prev => [sample, ...prev])
  }

  const labeledCount = samples.filter(s => !!s.human_labels || saveStatuses[s.id] === 'saved').length
  const totalCount = samples.length

  const visibleSamples = filter === 'unlabeled'
    ? samples.filter(s => !s.human_labels && saveStatuses[s.id] !== 'saved')
    : samples

  if (loading) {
    return (
      <div style={{ padding: '60px 24px', textAlign: 'center', color: 'var(--text2)' }}>
        Loading samples...
      </div>
    )
  }

  return (
    <div style={{ padding: '40px 24px', maxWidth: '760px', margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '8px' }}>
        <h2 style={{ fontFamily: 'var(--font-display)', fontSize: '28px' }}>Audio Labeling Studio</h2>
        <span className="muted" style={{ fontFamily: 'var(--font-mono)', fontSize: '13px' }}>
          {labeledCount} / {totalCount} labeled
        </span>
      </div>

      <BaselineRecorder onSampleAdded={handleSampleAdded} />

      {error && (
        <div style={{
          background: 'rgba(212, 130, 90, 0.1)',
          border: '1px solid rgba(212, 130, 90, 0.3)',
          color: 'var(--warm)',
          padding: '12px',
          borderRadius: 'var(--radius)',
          marginBottom: '20px',
          fontSize: '14px',
        }}>
          {error}
        </div>
      )}

      <div style={{ display: 'flex', gap: '8px', marginBottom: '24px' }}>
        <button
          className={filter === 'all' ? 'btn-primary' : 'btn-ghost'}
          onClick={() => setFilter('all')}
          style={{ fontSize: '13px', padding: '6px 16px' }}
        >
          All
        </button>
        <button
          className={filter === 'unlabeled' ? 'btn-primary' : 'btn-ghost'}
          onClick={() => setFilter('unlabeled')}
          style={{ fontSize: '13px', padding: '6px 16px' }}
        >
          Unlabeled only
        </button>
      </div>

      {visibleSamples.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--text2)' }}>
          {filter === 'unlabeled' ? 'All samples have been labeled.' : 'No samples found.'}
        </div>
      ) : (
        visibleSamples.map(sample => (
          <SampleCard
            key={sample.id}
            sample={sample}
            localEdits={edits[sample.id]}
            onEditChange={handleEditChange}
            onSave={handleSave}
            saveStatus={saveStatuses[sample.id] || null}
          />
        ))
      )}
    </div>
  )
}
