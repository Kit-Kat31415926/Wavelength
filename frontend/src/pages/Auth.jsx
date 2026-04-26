import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { forgotPassword, getUser, login, register, resetPassword } from '../lib/api'

export default function Auth() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [mode, setMode] = useState('login')
  const [displayName, setDisplayName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [resetToken, setResetToken] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')

  useEffect(() => {
    const urlMode = searchParams.get('mode')
    const token = searchParams.get('token') || ''
    if (urlMode === 'reset' && token) {
      setMode('reset')
      setResetToken(token)
      setPassword('')
      setConfirmPassword('')
      setError('')
      setInfo('Verification token received. Set your new password below.')
    }
  }, [searchParams])

  const handleModeSwitch = (nextMode) => {
    if (nextMode === mode) return
    setMode(nextMode)
    setDisplayName('')
    setEmail('')
    setPassword('')
    setConfirmPassword('')
    setResetToken('')
    setError('')
    setInfo('')
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setInfo('')

    if (mode === 'forgot') {
      if (!email.trim()) {
        setError('Email is required')
        return
      }

      setLoading(true)
      try {
        const res = await forgotPassword({ email: email.trim() })
        setInfo(res?.data?.message || 'If this email exists, a password reset link has been sent.')
      } catch (err) {
        setError(err?.response?.data?.detail || 'Could not send reset email')
      } finally {
        setLoading(false)
      }
      return
    }

    if (mode === 'reset') {
      if (!resetToken.trim()) {
        setError('Reset token is required')
        return
      }
      if (!password.trim()) {
        setError('New password is required')
        return
      }
      if (password.length < 8) {
        setError('Password must be at least 8 characters')
        return
      }
      if (password !== confirmPassword) {
        setError('Passwords do not match')
        return
      }

      setLoading(true)
      try {
        const res = await resetPassword({ token: resetToken.trim(), new_password: password })
        setMode('login')
        setPassword('')
        setConfirmPassword('')
        setResetToken('')
        setInfo(res?.data?.message || 'Password updated successfully. Please log in.')
      } catch (err) {
        setError(err?.response?.data?.detail || 'Could not reset password')
      } finally {
        setLoading(false)
      }
      return
    }

    if (mode === 'register' && !displayName.trim()) {
      setError('Display name is required')
      return
    }
    if (!email.trim() || !password.trim()) {
      setError('Email and password are required')
      return
    }
    if (mode === 'register' && password.length < 8) {
      setError('Password must be at least 8 characters')
      return
    }

    setLoading(true)
    try {
      const payload = mode === 'register'
        ? { email: email.trim(), password, display_name: displayName.trim() }
        : { email: email.trim(), password }

      const res = mode === 'register' ? await register(payload) : await login(payload)
      const token = res?.data?.token
      const user = res?.data?.user

      if (!token || !user) {
        throw new Error('Missing auth response data')
      }

      localStorage.setItem('wavelength_auth', JSON.stringify({ token, user }))
      const profileUserId = `auth-user-${user.id}`

      // Keep compatibility with existing app flow, which relies on wavelength_user.
      let hasProfile = false
      try {
        await getUser(profileUserId)
        hasProfile = true
      } catch {
        hasProfile = false
      }

      if (hasProfile) {
        localStorage.setItem('wavelength_user', JSON.stringify({
          user_id: profileUserId,
          name: user.display_name || user.email,
          profile_complete: true,
          is_demo_user: false,
        }))
        navigate('/matches')
      } else {
        localStorage.setItem('wavelength_user', JSON.stringify({
          user_id: profileUserId,
          name: user.display_name || user.email,
          profile_complete: false,
          is_demo_user: false,
        }))
        navigate('/onboard')
      }
    } catch (err) {
      setError(err?.response?.data?.detail || 'Authentication failed')
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ maxWidth: '520px', margin: '40px auto' }}>
      <h2 style={{ marginBottom: '8px' }}>
        {mode === 'register' && 'Create account'}
        {mode === 'login' && 'Welcome back'}
        {mode === 'forgot' && 'Forgot your password?'}
        {mode === 'reset' && 'Reset your password'}
      </h2>
      <p style={{ color: 'var(--text2)', marginBottom: '24px' }}>
        {mode === 'register' && 'Create your account, then build your profile and start matching.'}
        {mode === 'login' && 'Sign in to continue your profile, matches, and messages.'}
        {mode === 'forgot' && 'Enter your email and we will send a verification link to change your password.'}
        {mode === 'reset' && 'Set a new password for your account.'}
      </p>

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

      {info && (
        <div style={{
          background: 'rgba(108, 196, 138, 0.12)',
          border: '1px solid rgba(108, 196, 138, 0.4)',
          color: '#6cc48a',
          padding: '12px',
          borderRadius: 'var(--radius)',
          marginBottom: '16px',
          fontSize: '14px',
        }}>
          {info}
        </div>
      )}

      <form onSubmit={handleSubmit} style={{ display: 'grid', gap: '12px' }}>
        {mode === 'register' && (
          <input
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder='Display name'
            type='text'
            required
          />
        )}

        {(mode === 'register' || mode === 'login' || mode === 'forgot') && (
          <input
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder='Email'
            type='email'
            autoComplete='email'
            required
          />
        )}

        {mode === 'reset' && (
          <input
            value={resetToken}
            onChange={(e) => setResetToken(e.target.value)}
            placeholder='Verification token'
            type='text'
            autoComplete='off'
            required
          />
        )}

        {(mode === 'register' || mode === 'login' || mode === 'reset') && (
          <input
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder={mode === 'reset' ? 'New password' : 'Password'}
            type='password'
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            required
          />
        )}

        {mode === 'reset' && (
          <input
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            placeholder='Confirm new password'
            type='password'
            autoComplete='new-password'
            required
          />
        )}

        <button className='btn-primary' type='submit' disabled={loading}>
          {loading ? 'Please wait...' : (
            mode === 'register'
              ? 'Create account'
              : mode === 'login'
                ? 'Login'
                : mode === 'forgot'
                  ? 'Send verification email'
                  : 'Reset password'
          )}
        </button>
      </form>

      <div style={{ marginTop: '12px', display: 'flex', gap: '12px', flexDirection: 'column', alignItems: 'center' }}>
        {mode === 'login' && (
          <>
            <button
              type='button'
              onClick={() => handleModeSwitch('forgot')}
              style={{ background: 'none', border: 'none', padding: 0, color: 'var(--accent)', cursor: 'pointer' }}
            >
              Forgot password?
            </button>
            <button
              type='button'
              style={{ background: 'none', border: 'none', padding: 0, color: 'var(--accent)', cursor: 'pointer' }}
              onClick={() => handleModeSwitch('register')}
            >
              No account? Register today!
            </button>
          </>
        )}

        {(mode === 'forgot' || mode === 'reset') && (
          <button
            type='button'
            onClick={() => handleModeSwitch('login')}
            style={{ background: 'none', border: 'none', padding: 0, color: 'var(--accent)', cursor: 'pointer' }}
          >
            Back to login
          </button>
        )}

        {mode === 'register' && (
          <button
            type='button'
            style={{ background: 'none', border: 'none', padding: 0, color: 'var(--accent)', cursor: 'pointer' }}
            onClick={() => handleModeSwitch('login')}
          >
            Login with existing account
          </button>
        )}
      </div>

    </div>
  )
}