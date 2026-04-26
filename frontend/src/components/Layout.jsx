import { Link, useLocation, useNavigate } from 'react-router-dom'

export default function Layout({ children }) {
  const navigate = useNavigate()
  useLocation()
  const auth = JSON.parse(localStorage.getItem('wavelength_auth') || '{}')
  const isLoggedIn = Boolean(auth?.token)

  const handleLogout = () => {
    localStorage.removeItem('wavelength_auth')
    localStorage.removeItem('wavelength_user')
    navigate('/auth')
  }

  return (
    <>
      <nav className="nav">
        <div className="container" style={{ width: '100%', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Link to="/" className="nav-brand">
            <span>~Wavelength~</span>
          </Link>
          {isLoggedIn && (
            <ul className="nav-links">
              <li><Link to="/matches">Discover</Link></li>
              <li><Link to="/messages">Messages</Link></li>
              <li><Link to="/converse">Conversation</Link></li>
              <li><Link to="/portrait">My Profile</Link></li>
              <li>
                <button
                  type="button"
                  onClick={handleLogout}
                  style={{
                    background: 'none',
                    border: 'none',
                    color: 'inherit',
                    font: 'inherit',
                    cursor: 'pointer',
                    padding: 0,
                  }}
                >
                  Logout
                </button>
              </li>
            </ul>
          )}
          {!isLoggedIn && null}
        </div>
      </nav>
      <main className="container">
        {children}
      </main>
    </>
  )
}
