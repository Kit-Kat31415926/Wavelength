import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { createProfile } from '../lib/api'

export default function Onboard() {
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [age, setAge] = useState('')
  const [gender, setGender] = useState('')
  const [preferredAgeMin, setPreferredAgeMin] = useState('')
  const [preferredAgeMax, setPreferredAgeMax] = useState('')
  const [photoUrl, setPhotoUrl] = useState('')
  const [photoPreview, setPhotoPreview] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handlePhotoFileChange = (e) => {
    const file = e.target.files[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = (ev) => {
      setPhotoUrl(ev.target.result)
      setPhotoPreview(ev.target.result)
    }
    reader.readAsDataURL(file)
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!name.trim()) {
      setError('Please enter your name')
      return
    }
    if (!age) {
      setError('Please enter your age')
      return
    }
    if (!gender.trim()) {
      setError('Please enter your gender')
      return
    }
    if (!photoUrl) {
      setError('Please upload a photo')
      return
    }
    if (preferredAgeMin && preferredAgeMax && parseInt(preferredAgeMin) > parseInt(preferredAgeMax)) {
      setError('Preferred age minimum cannot be greater than maximum')
      return
    }

    setLoading(true)
    try {
      const existing = JSON.parse(localStorage.getItem('wavelength_user') || '{}')
      const userId = existing.user_id || crypto.randomUUID()
      await createProfile({
        user_id: userId,
        name,
        age: age ? parseInt(age) : null,
        gender: gender || null,
        photo_url: photoUrl,
        preferred_age_min: preferredAgeMin ? parseInt(preferredAgeMin) : null,
        preferred_age_max: preferredAgeMax ? parseInt(preferredAgeMax) : null,
      })
      
      localStorage.setItem('wavelength_user', JSON.stringify({ user_id: userId, name, profile_complete: true }))
      navigate('/converse')
    } catch (err) {
      setError('Failed to create profile. Please try again.')
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ padding: '60px 0' }}>
      <div style={{ maxWidth: '400px', margin: '0 auto' }}>
        <h2 style={{ marginBottom: '8px' }}>Let's get to know you</h2>
        <p className="muted" style={{ marginBottom: '32px', fontSize: '14px' }}>
          What should we call you?
        </p>

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

        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: '20px' }}>
            <label style={{ display: 'block', marginBottom: '8px', fontSize: '14px' }}>
              Name <span style={{ color: 'var(--text3)' }}>*</span>
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </div>

          <div style={{ marginBottom: '20px' }}>
            <label style={{ display: 'block', marginBottom: '8px', fontSize: '14px' }}>
              Age <span style={{ color: 'var(--text3)' }}>*</span>
            </label>
            <input
              type="number"
              value={age}
              onChange={(e) => setAge(e.target.value)}
              min="18"
              max="120"
              required
            />
          </div>

          <div style={{ marginBottom: '20px' }}>
            <label style={{ display: 'block', marginBottom: '8px', fontSize: '14px' }}>
              Gender <span style={{ color: 'var(--text3)' }}>*</span>
            </label>
            <input
              type="text"
              value={gender}
              onChange={(e) => setGender(e.target.value)}
              required
            />
          </div>

          <div style={{ marginBottom: '20px' }}>
            <label style={{ display: 'block', marginBottom: '8px', fontSize: '14px' }}>
              Photo <span style={{ color: 'var(--text3)' }}>*</span>
            </label>
            <input
              type="file"
              accept="image/*"
              onChange={handlePhotoFileChange}
              required={!photoUrl}
              style={{ fontSize: '14px' }}
            />
            {photoPreview && (
              <div style={{ marginTop: '12px' }}>
                <img
                  src={photoPreview}
                  alt="Preview"
                  style={{
                    width: '80px',
                    height: '80px',
                    borderRadius: '8px',
                    objectFit: 'cover',
                    border: '1px solid var(--border)'
                  }}
                />
              </div>
            )}
          </div>

          <div style={{ marginBottom: '20px' }}>
            <label style={{ display: 'block', marginBottom: '8px', fontSize: '14px' }}>
              Preferred match age range <span style={{ color: 'var(--text2)' }}>(optional)</span>
            </label>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
              <input
                type="number"
                value={preferredAgeMin}
                onChange={(e) => setPreferredAgeMin(e.target.value)}
                min="18"
                max="120"
                placeholder="Min age"
              />
              <input
                type="number"
                value={preferredAgeMax}
                onChange={(e) => setPreferredAgeMax(e.target.value)}
                min="18"
                max="120"
                placeholder="Max age"
              />
            </div>
          </div>

          <button 
            type="submit" 
            className="btn-primary"
            style={{ width: '100%', marginTop: '32px' }}
            disabled={loading}
          >
            {loading ? 'Creating profile...' : 'Begin Conversation'}
          </button>
        </form>
      </div>
    </div>
  )
}
