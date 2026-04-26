import axios from 'axios'

const API = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000'
})

export const createProfile = (data) => API.post('/profile/create', data)
export const register = (data) => API.post('/auth/register', data)
export const login = (data) => API.post('/auth/login', data)
export const forgotPassword = (data) => API.post('/auth/forgot-password', data)
export const resetPassword = (data) => API.post('/auth/reset-password', data)
export const me = (token) => API.get('/auth/me', {
  headers: { Authorization: `Bearer ${token}` },
})
export const seedDemoUsers = () => API.post('/seed-demo-users')
export const getUsers = () => API.get('/users')
export const getUser = (id) => API.get(`/users/${id}`)
export const getPotentialMatches = (userId, limit = 30) => API.get(`/match/potential/${userId}?limit=${limit}`)
export const startInterview = (data, config = {}) => API.post('/interview/start', data, config)
export const sendMessage = (data, config = {}) => API.post('/interview/chat', data, config)
export const sendMessageAudio = (data, config = {}) => API.post('/interview/chat-audio', data, config)
export const textToSpeech = (data, config = {}) => API.post('/api/text-to-speech', data, {
  responseType: 'blob',
  ...config
})
export const extractWavelengthlity = (data) => API.post('/interview/extract', data)
export const getCompatibility = (data) => API.post('/match/compatibility', data)
export const getSimulation = (data) => API.post('/match/simulate', data)
export const sendDM = (data) => API.post('/dm/send', data)
export const getDMs = (userIdA, userIdB) => API.get(`/dm/${userIdA}/${userIdB}`)
export const getConversations = (userId) => API.get(`/dm/conversations/${userId}`)
export const sendMeetupFeedback = (data) => API.post('/dm/meetup-feedback', data)
export const unmatch = (data) => API.post('/dm/unmatch', data)
