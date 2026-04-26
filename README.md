# Wavelength

For everyone who is in need of a friend, or just wants to add some spice in their life by meeting someone new, \~Wavelength\~ is a friendship matching app that unveils your true personality through a conversational environment to find others who will just *click* with you on a deeper level. Based off the YC startup "Dating Ring" (Winter 2014), \~Wavelength\~ uses artificial intelligence to analyze how humans think and interact in order to determine their next best friend.

**Built by:** Kaitlyn Chiu, Ritali Jain, Arnav Dixit

**Built for:** HackTech 2026

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| **Frontend** | React 18 + Vite + React Router |
| **Backend** | Python FastAPI |
| **Database** | SQLite |
| **AI — Conversation** | Google Gemini (Gemma4) |
| **AI — Reasoning** | K2 Think V2 |
| **Charts** | Recharts |
| **Audio** | Web Speech API (input) · ElevenLabs (TTS output) |
| **Auth** | JWT tokens + SQLite |
| **UI Components** | Lucide React icons |

---

## Setup Instructions

### Prerequisites
- Python 3.9+
- Node.js 18+
- API Keys: Google AI (required), K2 (required), ElevenLabs (optional)

### Backend (Terminal 1)

```bash
cd backend
python -m venv venv
source venv/bin/activate              # Windows: venv\Scripts\activate
pip install -r requirements.txt

nano .env
# Create .env and add:
# GOOGLE_API_KEY=your-google-api-key
# K2_API_KEY=your-k2-key
# ELEVENLABS_API_KEY=your-elevenlabs-key (optional)

uvicorn main:app --reload --port 8000
```

**Verify:** `curl http://localhost:8000/health` → `{"status":"ok"}`

### Frontend (Terminal 2)

```bash
cd frontend
npm install
npm run dev
```

**Open:** `http://localhost:5173`

---

## Key Features

### Conversation
- Natural AI interview (Gemma 4 and K2 Think V2) instead of quiz
- Adaptive questioning based on responses
- Optional voice mode (Web Speech API + ElevenLabs)
- 5-10 turns, then graceful completion

### Wavelengthlity Profile
- AI-extracted personality profile (7 traits: 0.0-1.0)
- Values, interests, worldview
- Conflict style, communication register
- Radar chart visualization

### Deep Compatibility Matching
- K2 Think V2 reasons through two profiles (6 dimensions)
- Multi-dimensional scoring: traits, values, lifestyle, communication, emotional, intellectual, growth
- Compatibility analysis with strengths and friction points
- Age preference filtering

### First Chat Simulation
- K2-generated realistic conversation
- Shows vocabulary, question patterns, dynamics
- Models how two humans think and align

### Direct Messaging
- Real-time chat between matched users
- Persistent message history
- Meetup feedback collection

### Audio Personality Analysis
- Extracts speech patterns (pitch, energy, pauses, spectral features)
- Auto-labels for training ML models
- Calibration per user session

---

## API Reference

### Health
- `GET /health` — Server status

### Authentication
- `POST /auth/register` — Create account
- `POST /auth/login` — Get JWT token
- `GET /auth/me` — Get authenticated user
- `POST /auth/forgot-password` — Request reset
- `POST /auth/reset-password` — Reset password

### Profile
- `POST /profile/create` — Create user profile
- `GET /users` — List all users
- `GET /users/{user_id}` — Get specific user

### Interview
- `POST /interview/start` — Begin new session
- `POST /interview/chat` — Send text message
- `POST /interview/chat-audio` — Send audio message
- `POST /interview/extract` — Extract wavelengthlity

### Matching
- `GET /match/potential/{user_id}` — Get ranked matches
- `POST /match/compatibility` — K2 analysis (2 users)
- `POST /match/simulate` — K2 conversation simulation

### Direct Messaging
- `POST /dm/send` — Send message
- `GET /dm/{user_id_a}/{user_id_b}` — Get conversation
- `GET /dm/conversations/{user_id}` — List conversations
- `POST /dm/meetup-feedback` — Record date feedback
- `POST /dm/unmatch` — Remove match

### Voice
- `POST /api/text-to-speech` — Text → speech (ElevenLabs)

### Audio Analysis (Labeling)
- `GET /audio/samples` — List samples
- `POST /audio/label` — Label audio features
- `GET /audio/samples/{session_id}/{turn}/file` — Download audio
- `POST /audio/samples/upload` — Upload audio

### Demo & Testing
- `POST /seed-demo-users` — Populate 6 demo profiles
- `POST /seed-test-user` — Create test user

---

## Getting API Keys

**Google API Key** (Free - Gemini for interviews)
1. Go to [Google AI Studio](https://aistudio.google.com/app/apikey)
2. Click "Get API Key"
3. Add to `.env`: `GOOGLE_API_KEY=your-key`

**K2 API Key** (Required - Reasoning for matching)
1. Get from IFM (provided at Hacktech)
2. Add to `.env`: `K2_API_KEY=your-key`

**ElevenLabs API Key** (Optional - Voice output)
1. Go to [ElevenLabs](https://elevenlabs.io)
2. Sign up and copy API key
3. Add to `.env`: `ELEVENLABS_API_KEY=your-key`

---

## Demo Flow

1. **Landing** → Click to begin your portrait
2. **Onboard** → Enter name, age, photo, etc
3. **Interview** → Chat naturally with Gemini (~5-10 turns)
   - Toggle voice mode to speak & hear responses
   - Toggle text mode to type and read responses
4. **Portrait** → View your profile based on deep AI analysis
5. **Matches** → Click to view best 3 matches
   - Click match for compatibility analysis (K2 Think V2)
   - Click "Simulate Conversation" to see K2 Think V2 dialogue
6. **Chat** → Send/receive direct messages

---

## Important Notes

- **SQLite persistence** — User profiles, messages, auth stored in local database
- **Gemini for conversation** — Fast, natural dialogue via Google AI (Gemma 4)
- **K2 Think V2 for reasoning** — Multi-step inference for compatibility matching
- **Audio analysis** — Extracts personality traits from speech patterns
- **Age filtering** — Respects user age preferences in matching

---

## What's Next (Post-Hackathon)

1. PostgreSQL migration (from SQLite)
2. Server-Sent Events for real-time chat
3. Run LLM models locally for lower latency
4. Cloud deployment (Railway, Render)
5. Mobile optimization (responsive design)
6. Advanced filters (interests, location, preferences)
7. Subscription tiers
8. Admin dashboard for analytics
