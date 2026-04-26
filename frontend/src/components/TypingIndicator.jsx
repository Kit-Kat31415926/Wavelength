export default function TypingIndicator() {
  return (
    <div style={{ display: 'flex', gap: '4px', padding: '12px 16px' }}>
      <span style={{
        width: '8px',
        height: '8px',
        borderRadius: '50%',
        background: 'var(--text2)',
        animation: 'pulse 0.9s infinite',
        animationDelay: '0s'
      }}></span>
      <span style={{
        width: '8px',
        height: '8px',
        borderRadius: '50%',
        background: 'var(--text2)',
        animation: 'pulse 0.9s infinite',
        animationDelay: '0.15s'
      }}></span>
      <span style={{
        width: '8px',
        height: '8px',
        borderRadius: '50%',
        background: 'var(--text2)',
        animation: 'pulse 0.9s infinite',
        animationDelay: '0.3s'
      }}></span>
    </div>
  )
}
