import { Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import Landing from './pages/Landing'
import Auth from './pages/Auth'
import Onboard from './pages/Onboard'
import Conversation from './pages/Conversation'
import Portrait from './pages/Portrait'
import Matches from './pages/Matches'
import Chat from './pages/Chat'
import LabelingStudio from './pages/LabelingStudio'
import Messages from './pages/Messages'

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/auth" element={<Auth />} />
        <Route path="/onboard" element={<Onboard />} />
        <Route path="/converse" element={<Conversation />} />
        <Route path="/portrait" element={<Portrait />} />
        <Route path="/matches" element={<Matches />} />
        <Route path="/chat/:matchId" element={<Chat />} />
        <Route path="/label" element={<LabelingStudio />} />
        <Route path="/messages" element={<Messages />} />
      </Routes>
    </Layout>
  )
}
