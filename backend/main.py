from fastapi import FastAPI, HTTPException, Header, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional
import re
import google.generativeai, httpx, json, os, uuid, io, wave, audioop, math
from datetime import datetime
import hashlib
import secrets
import sqlite3
import time
import smtplib
from email.message import EmailMessage
from dotenv import load_dotenv, find_dotenv
from elevenlabs import ElevenLabs, VoiceSettings
import numpy as np

load_dotenv(find_dotenv(filename='.env', raise_error_if_not_found=False))

GOOGLE_API_KEY      = os.getenv("GOOGLE_API_KEY", "")
K2_API_KEY          = os.getenv("K2_API_KEY", "")
K2_BASE_URL         = os.getenv("K2_BASE_URL", "https://api.k2think.ai/v1")
ELEVENLABS_API_KEY  = os.getenv("ELEVENLABS_API_KEY", "") or os.getenv("ELEVEN_LABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")
DATABASE_PATH       = os.getenv("DATABASE_PATH", os.path.join(os.path.dirname(__file__), "wavelength.db"))
FRONTEND_URL        = os.getenv("FRONTEND_URL", "http://localhost:5173")
SMTP_HOST           = os.getenv("SMTP_HOST", "")
SMTP_PORT           = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER           = os.getenv("SMTP_USER", "")
SMTP_PASS           = os.getenv("SMTP_PASS", "")
SMTP_FROM           = os.getenv("SMTP_FROM", SMTP_USER or "no-reply@wavelength.local")
SMTP_USE_TLS        = os.getenv("SMTP_USE_TLS", "true").lower() == "true"

allowed_origins = [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:5175",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5174",
    "http://127.0.0.1:5175",
    "https://wwwavelength.tech",
    "https://www.wwwavelength.tech",
    FRONTEND_URL.rstrip("/"),
]

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(dict.fromkeys(origin for origin in allowed_origins if origin)),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

elevenlabs_client = ElevenLabs(api_key=ELEVENLABS_API_KEY) if ELEVENLABS_API_KEY else None

# In-memory store (sufficient for hackathon demo)
users_db: dict = {}    # user_id -> profile dict
sessions_db: dict = {} # session_id -> message list
direct_messages_db: dict = {} # conversation_key -> list of messages
session_audio_insights: dict = {} # session_id -> audio metadata
session_audio_history: dict = {}  # session_id -> list of per-turn raw feature dicts
unmatches_db: set = set()  # frozenset pairs of unmatched user_ids


def _get_db_conn():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _unmatch_key(a: str, b: str) -> frozenset:
    return frozenset([a, b])


def _is_unmatched(a: str, b: str) -> bool:
    return _unmatch_key(a, b) in unmatches_db


def _load_unmatches_from_db():
    """Load all unmatches from SQLite into the in-memory set."""
    conn = _get_db_conn()
    rows = conn.execute("SELECT user_id_a, user_id_b FROM unmatches").fetchall()
    conn.close()
    for row in rows:
        unmatches_db.add(frozenset([row["user_id_a"], row["user_id_b"]]))


def init_db():
    conn = _get_db_conn()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS profiles (
            user_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            age INTEGER,
            gender TEXT,
            photo_url TEXT,
            wavelengthlity_json TEXT,
            preferred_age_min INTEGER,
            preferred_age_max INTEGER
        )
        """
    )
    existing_columns = {
        row["name"] for row in cur.execute("PRAGMA table_info(profiles)").fetchall()
    }
    if "preferred_age_min" not in existing_columns:
        cur.execute("ALTER TABLE profiles ADD COLUMN preferred_age_min INTEGER")
    if "preferred_age_max" not in existing_columns:
        cur.execute("ALTER TABLE profiles ADD COLUMN preferred_age_max INTEGER")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS direct_messages (
            id TEXT PRIMARY KEY,
            conversation_key TEXT NOT NULL,
            from_user_id TEXT NOT NULL,
            to_user_id TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_dm_conversation_key ON direct_messages(conversation_key)")

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS auth_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            display_name TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS auth_tokens (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            expires_at INTEGER NOT NULL,
            FOREIGN KEY (user_id) REFERENCES auth_users(id)
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_auth_tokens_user_id ON auth_tokens(user_id)")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            expires_at INTEGER NOT NULL,
            used_at INTEGER,
            created_at INTEGER NOT NULL,
            FOREIGN KEY (user_id) REFERENCES auth_users(id)
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_password_reset_user_id ON password_reset_tokens(user_id)")

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS unmatches (
            user_id_a TEXT NOT NULL,
            user_id_b TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (user_id_a, user_id_b)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS meetup_feedback (
            id TEXT PRIMARY KEY,
            from_user_id TEXT NOT NULL,
            to_user_id TEXT NOT NULL,
            conversation_key TEXT NOT NULL,
            met INTEGER NOT NULL,
            chemistry_rating INTEGER,
            communication_rating INTEGER,
            safety_rating INTEGER,
            would_meet_again INTEGER,
            notes TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_meetup_feedback_from_user ON meetup_feedback(from_user_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_meetup_feedback_conversation ON meetup_feedback(conversation_key)")

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS audio_labels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            turn INTEGER NOT NULL,
            audio_path TEXT,
            features_json TEXT NOT NULL,
            auto_labels_json TEXT NOT NULL,
            human_labels_json TEXT,
            created_at INTEGER NOT NULL,
            UNIQUE(session_id, turn)
        )
        """
    )

    conn.commit()
    conn.close()


def _db_upsert_profile(profile: dict):
    conn = _get_db_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO profiles (user_id, name, age, gender, photo_url, wavelengthlity_json, preferred_age_min, preferred_age_max)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            name=excluded.name,
            age=excluded.age,
            gender=excluded.gender,
            photo_url=excluded.photo_url,
            wavelengthlity_json=excluded.wavelengthlity_json,
            preferred_age_min=excluded.preferred_age_min,
            preferred_age_max=excluded.preferred_age_max
        """,
        (
            profile.get("user_id"),
            profile.get("name"),
            profile.get("age"),
            profile.get("gender"),
            profile.get("photo_url"),
            json.dumps(profile.get("wavelengthlity")) if profile.get("wavelengthlity") is not None else None,
            profile.get("preferred_age_min"),
            profile.get("preferred_age_max"),
        ),
    )
    conn.commit()
    conn.close()


def _sync_profiles_to_db():
    conn = _get_db_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM profiles")
    for profile in users_db.values():
        cur.execute(
            """
            INSERT INTO profiles (user_id, name, age, gender, photo_url, wavelengthlity_json, preferred_age_min, preferred_age_max)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile.get("user_id"),
                profile.get("name"),
                profile.get("age"),
                profile.get("gender"),
                profile.get("photo_url"),
                json.dumps(profile.get("wavelengthlity")) if profile.get("wavelengthlity") is not None else None,
                profile.get("preferred_age_min"),
                profile.get("preferred_age_max"),
            ),
        )
    conn.commit()
    conn.close()


def _load_profiles_from_db():
    users_db.clear()
    conn = _get_db_conn()
    cur = conn.cursor()
    for row in cur.execute("SELECT user_id, name, age, gender, photo_url, wavelengthlity_json, preferred_age_min, preferred_age_max FROM profiles"):
        users_db[row["user_id"]] = {
            "user_id": row["user_id"],
            "name": row["name"],
            "age": row["age"],
            "gender": row["gender"],
            "photo_url": row["photo_url"],
            "wavelengthlity": json.loads(row["wavelengthlity_json"]) if row["wavelengthlity_json"] else None,
            "preferred_age_min": row["preferred_age_min"],
            "preferred_age_max": row["preferred_age_max"],
        }
    conn.close()


def _transcribe_with_fillers(audio_bytes: bytes, fallback: str = "") -> str:
    """Transcribe audio via Gemini REST API, preserving filler words the browser strips."""
    if not GOOGLE_API_KEY or not audio_bytes:
        return fallback
    try:
        import base64
        payload = {
            "contents": [{
                "parts": [
                    {"inline_data": {"mime_type": "audio/wav", "data": base64.b64encode(audio_bytes).decode()}},
                    {"text": (
                        "Transcribe this speech exactly as spoken. "
                        "Preserve all filler words and hesitations (um, uh, like, you know, sort of, I mean, kind of). "
                        "Preserve false starts and repetitions. "
                        "Return ONLY the raw transcript — no punctuation cleanup, no explanations."
                    )},
                ]
            }]
        }
        resp = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GOOGLE_API_KEY}",
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        return text if text else fallback
    except Exception as e:
        print(f"[TRANSCRIBE] Filler transcription failed: {e}")
        return fallback


async def _process_audio_file(data: bytes) -> dict:
    content = data
    try:
        with wave.open(io.BytesIO(content), 'rb') as wav_file:
            channels = wav_file.getnchannels()
            sample_rate = wav_file.getframerate()
            sample_width = wav_file.getsampwidth()
            frames = wav_file.getnframes()
            duration_sec = frames / float(sample_rate)
            raw = wav_file.readframes(frames)

            if sample_width != 2:
                raw = audioop.lin2lin(raw, sample_width, 2)
                sample_width = 2

            pcm = np.frombuffer(raw, dtype=np.int16)
            if channels > 1:
                pcm = pcm.reshape(-1, channels).mean(axis=1)
            samples = pcm.astype(np.float32) / 32768.0
            samples = samples[: max(1, len(samples))]

            # Basic features that should always work
            overall_rms = float(np.sqrt(np.mean(np.square(samples))))
            approx_db = float(20 * math.log10(max(overall_rms, 1e-9)))
            zcr = float(np.mean(np.abs(np.diff(np.sign(samples)))) / 2.0)

            # More complex features with error handling
            try:
                frame_len = max(512, int(sample_rate * 0.04))
                hop = max(256, frame_len // 2)
                if len(samples) < frame_len:
                    frames_data = np.array([samples])
                else:
                    frames_data = np.stack([
                        samples[i:i + frame_len]
                        for i in range(0, len(samples) - frame_len + 1, hop)
                    ])

                frame_rms = np.sqrt(np.mean(np.square(frames_data), axis=1))
                energy_threshold = max(0.015, np.percentile(frame_rms, 65) * 0.4)
                voiced = frame_rms >= energy_threshold
                voiced_frames = int(np.sum(voiced))
                voiced_ratio = float(voiced_frames / len(frame_rms)) if len(frame_rms) else 0.0
                rms_variance = float(np.var(frame_rms))

                segment_count = 0
                pause_chunks = []
                current_pause = 0
                prev_voiced = False
                # 0.5s minimum: filters inter-word gaps (50–150ms) so only genuine
                # pauses (thinking, breath, deliberate silence) are counted
                min_pause_frames = max(2, int(0.5 * sample_rate / hop))
                for is_voiced in voiced:
                    if is_voiced:
                        if not prev_voiced:
                            segment_count += 1
                        if current_pause >= min_pause_frames:
                            pause_chunks.append(current_pause)
                        current_pause = 0
                    else:
                        current_pause += 1
                    prev_voiced = is_voiced
                if current_pause >= min_pause_frames:
                    pause_chunks.append(current_pause)

                pause_count = len(pause_chunks)
                pause_durations = [chunk * hop / sample_rate for chunk in pause_chunks]
                avg_pause_sec = float(np.mean(pause_durations)) if pause_durations else 0.0
                max_pause_sec = float(max(pause_durations)) if pause_durations else 0.0
                segment_rate = float(segment_count / duration_sec) if duration_sec > 0 else 0.0
                voiced_duration = float(voiced_frames * hop / sample_rate)
                # pause_ratio: all unvoiced / total — broad energy density measure,
                # NOT a hesitancy indicator (inter-word gaps inflate it for fluent speakers)
                pause_ratio = float(max(0.0, duration_sec - voiced_duration) / duration_sec) if duration_sec > 0 else 0.0
                # meaningful_pause_ratio: only pauses >= 0.5s; used for deliberateness scoring
                meaningful_pause_ratio = float(sum(pause_durations) / duration_sec) if duration_sec > 0 else 0.0
            except Exception as e:
                print(f"[AUDIO] Frame analysis failed: {e}")
                voiced_ratio = 0.5
                rms_variance = 0.0
                segment_count = 1
                segment_rate = 1.0
                avg_pause_sec = 0.0
                max_pause_sec = 0.0
                pause_ratio = 0.0
                pause_count = 0
                meaningful_pause_ratio = 0.0

            # Pitch and spectral features with error handling
            try:
                pitch_median, pitch_std, pitch_min, pitch_max = _estimate_pitch_statistics(samples, sample_rate)
                pitch_range = (pitch_max - pitch_min) if pitch_min > 0 and pitch_max > 0 else 0.0
                spectral_centroid = _compute_spectral_centroid(samples, sample_rate)
                spectral_flatness = _compute_spectral_flatness(samples)
                spectral_rolloff = _compute_spectral_rolloff(samples, sample_rate)
                spectral_flux = _compute_spectral_flux(samples, sample_rate)
            except Exception as e:
                print(f"[AUDIO] Spectral analysis failed: {e}")
                pitch_median, pitch_std, pitch_range = 0.0, 0.0, 0.0
                spectral_centroid = 0.0
                spectral_flatness = 0.0
                spectral_rolloff = 0.0
                spectral_flux = 0.0

            energy_cv = float(rms_variance ** 0.5 / max(overall_rms, 1e-9))

            features = {
                'duration_seconds': round(duration_sec, 3),
                'sample_rate': sample_rate,
                'channels': channels,
                'sample_width': sample_width,
                'rms': round(overall_rms, 6),
                'approx_db': round(approx_db, 2),
                'energy_cv': round(energy_cv, 4),
                'zero_crossing_rate': round(zcr, 4),
                'voiced_ratio': round(voiced_ratio, 4),
                'segment_count': int(segment_count),
                'segment_rate': round(segment_rate, 3),
                'pause_count': int(pause_count),
                'avg_pause_sec': round(avg_pause_sec, 3),
                'max_pause_sec': round(max_pause_sec, 3),
                'pause_ratio': round(pause_ratio, 4),
                'meaningful_pause_ratio': round(meaningful_pause_ratio, 4),
                'pitch_median_hz': round(pitch_median, 2),
                'pitch_std_hz': round(pitch_std, 2),
                'pitch_range_hz': round(pitch_range, 2),
                'spectral_centroid_hz': round(spectral_centroid, 2),
                'spectral_flux': round(spectral_flux, 2),
                'spectral_flatness': round(spectral_flatness, 4),
                'spectral_rolloff_hz': round(spectral_rolloff, 2),
                'rms_variance': round(rms_variance, 6),
            }

            print(f"[AUDIO] Extracted features: {duration_sec:.1f}s, {approx_db:.1f}dB")
            return features
    except wave.Error:
        raise HTTPException(status_code=400, detail='Unsupported audio format. Please upload WAV audio.')
    except Exception as e:
        print(f"[AUDIO] Unexpected error in audio processing: {e}")
        raise HTTPException(status_code=500, detail='Audio processing failed. Please try again.')


def _estimate_pitch_statistics(samples: np.ndarray, sample_rate: int) -> tuple[float, float, float, float]:
    max_window = min(len(samples), sample_rate * 2)
    if max_window < 1024:
        return 0.0, 0.0, 0.0, 0.0

    frame_len = max_window
    hop = frame_len // 2
    pitches = []
    window = np.hamming(frame_len)
    for start in range(0, len(samples) - frame_len + 1, hop):
        frame = samples[start:start + frame_len] * window
        frame -= np.mean(frame)
        autocorr = np.correlate(frame, frame, mode='full')[frame_len - 1:]
        min_lag = int(sample_rate / 400)
        max_lag = int(sample_rate / 80)
        if max_lag <= min_lag:
            continue
        autocorr[:min_lag] = 0
        peak = int(np.argmax(autocorr[min_lag:max_lag]) + min_lag)
        if peak > 0 and autocorr[peak] > 0:
            freq = sample_rate / peak
            if 50 <= freq <= 450:
                pitches.append(freq)
    if not pitches:
        return 0.0, 0.0, 0.0, 0.0
    return float(np.median(pitches)), float(np.std(pitches)), float(np.min(pitches)), float(np.max(pitches))


def _compute_spectral_flux(samples: np.ndarray, sample_rate: int) -> float:
    frame_len = min(len(samples), max(512, int(sample_rate * 0.05)))
    hop = frame_len // 2
    if len(samples) < frame_len:
        return 0.0
    centroids = []
    for start in range(0, len(samples) - frame_len + 1, hop):
        frame = samples[start:start + frame_len] * np.hamming(frame_len)
        spectrum = np.abs(np.fft.rfft(frame))
        freqs = np.fft.rfftfreq(frame_len, 1.0 / sample_rate)
        total = np.sum(spectrum)
        if total > 0:
            centroids.append(float(np.sum(freqs * spectrum) / total))
    if len(centroids) < 2:
        return 0.0
    return float(np.mean(np.abs(np.diff(centroids))))


def _compute_spectral_centroid(samples: np.ndarray, sample_rate: int) -> float:
    length = min(len(samples), 4096)
    frame = samples[:length] * np.hamming(length)
    spectrum = np.abs(np.fft.rfft(frame))
    freqs = np.fft.rfftfreq(length, 1.0 / sample_rate)
    if np.sum(spectrum) <= 0:
        return 0.0
    return float(np.sum(freqs * spectrum) / np.sum(spectrum))


def _compute_spectral_flatness(samples: np.ndarray) -> float:
    length = min(len(samples), 4096)
    frame = samples[:length] * np.hamming(length)
    spectrum = np.abs(np.fft.rfft(frame)) + 1e-12
    geometric_mean = np.exp(np.mean(np.log(spectrum)))
    arithmetic_mean = np.mean(spectrum)
    return float(geometric_mean / arithmetic_mean) if arithmetic_mean > 0 else 0.0


def _compute_spectral_rolloff(samples: np.ndarray, sample_rate: int, rolloff_pct: float = 0.85) -> float:
    length = min(len(samples), 4096)
    frame = samples[:length] * np.hamming(length)
    spectrum = np.abs(np.fft.rfft(frame))
    freqs = np.fft.rfftfreq(length, 1.0 / sample_rate)
    energy = np.cumsum(spectrum)
    threshold = energy[-1] * rolloff_pct
    idx = np.searchsorted(energy, threshold)
    return float(freqs[min(idx, len(freqs) - 1)])


_CALIBRATION_KEYS = ['energy_cv', 'segment_rate', 'voiced_ratio', 'pause_ratio', 'pitch_std_hz', 'pitch_range_hz', 'spectral_flux', 'spectral_centroid_hz']
_CALIBRATION_MIN_STD = {'energy_cv': 0.02, 'segment_rate': 0.05, 'voiced_ratio': 0.02, 'pause_ratio': 0.02, 'pitch_std_hz': 2.0, 'pitch_range_hz': 5.0, 'spectral_flux': 10.0, 'spectral_centroid_hz': 50.0}

_FILLERS = re.compile(r'\b(um+|uh+|erm+|hmm+|like|you know|kind of|sort of|you see|i mean)\b', re.I)
_HEDGES = re.compile(r'\b(maybe|perhaps|probably|possibly|i think|i guess|i suppose|i feel like|not sure|i\'m not sure|might|could be|kind of|sort of)\b', re.I)
_RESTARTS = re.compile(r'\b(actually|wait|no wait|well|so basically|anyway|i was going to say)\b', re.I)


def _extract_transcript_signals(transcript: str) -> dict:
    if not transcript or not transcript.strip():
        return {}
    words = transcript.lower().split()
    word_count = len(words)
    if word_count == 0:
        return {}
    unique_words = len(set(words))
    sentence_count = max(1, len(re.findall(r'[.!?]+', transcript)))
    filler_count = len(_FILLERS.findall(transcript))
    hedge_count = len(_HEDGES.findall(transcript))
    restart_count = len(_RESTARTS.findall(transcript))
    question_count = transcript.count('?')
    return {
        'word_count': word_count,
        'vocab_diversity': round(unique_words / word_count, 3),
        'filler_rate': round(filler_count / word_count, 3),
        'hedge_ratio': round(hedge_count / word_count, 3),
        'restart_rate': round(restart_count / sentence_count, 3),
        'question_count': question_count,
        'question_ratio': round(question_count / sentence_count, 3),
        'response_category': 'brief' if word_count < 15 else ('elaborate' if word_count > 50 else 'moderate'),
    }


def _compute_session_calibration(history: list, features: dict) -> dict:
    if not history:
        return {}
    cal = {'n_prior_turns': len(history)}
    for key in _CALIBRATION_KEYS:
        vals = [h[key] for h in history if isinstance(h.get(key), (int, float))]
        if not vals:
            continue
        mean = sum(vals) / len(vals)
        variance = sum((v - mean) ** 2 for v in vals) / len(vals)
        std = max(variance ** 0.5, _CALIBRATION_MIN_STD[key])
        current = features.get(key, mean)
        cal[f'{key}_baseline'] = round(mean, 3)
        cal[f'{key}_zscore'] = round((current - mean) / std, 2)
    ecv_z = cal.get('energy_cv_zscore', 0)
    cadence_z = cal.get('segment_rate_zscore', 0)
    voiced_z = cal.get('voiced_ratio_zscore', 0)
    cal['relative_energy'] = 'above_baseline' if ecv_z > 0.6 else ('below_baseline' if ecv_z < -0.6 else 'at_baseline')
    cal['relative_cadence'] = 'faster_than_usual' if cadence_z > 0.6 else ('slower_than_usual' if cadence_z < -0.6 else 'typical')
    cal['relative_engagement'] = 'more_engaged' if voiced_z > 0.6 else ('less_engaged' if voiced_z < -0.6 else 'typical')
    return cal


def _classify_audio_style_from_features(features: dict, calibration: dict = None, transcript_signals: dict = None) -> dict:
    labels = {}
    ts = transcript_signals or {}
    energy_cv = features.get('energy_cv', 0.0)
    approx_db = features.get('approx_db', -25.0)
    centroid = features.get('spectral_centroid_hz', 0)
    spectral_flux = features.get('spectral_flux', 0.0)
    cadence = features.get('segment_rate', 0)
    pause_ratio = features.get('pause_ratio', 0)
    meaningful_pause_ratio = features.get('meaningful_pause_ratio', 0.0)
    avg_pause_sec = features.get('avg_pause_sec', 0.0)
    pause_count = features.get('pause_count', 0)
    voiced_ratio = features.get('voiced_ratio', 0)
    pitch_median = features.get('pitch_median_hz', 0)
    pitch_std = features.get('pitch_std_hz', 0)
    pitch_range = features.get('pitch_range_hz', 0.0)
    spectral_flatness = features.get('spectral_flatness', 0)

    pitch_variability = pitch_std / max(pitch_median, 50)

    # volume_style derived from actual loudness (approx_db), not energy variance
    # energy_cv measures dynamics/expressiveness, not volume — a quiet expressive
    # speaker has high energy_cv but is not "loud"
    if approx_db > -15:
        labels['volume_style'] = 'loud'
    elif approx_db < -30:
        labels['volume_style'] = 'soft_spoken'
    else:
        labels['volume_style'] = 'moderate'

    # expressiveness: how much energy varies across the clip
    if energy_cv > 0.8:
        labels['expressiveness'] = 'highly_expressive'
    elif energy_cv < 0.3:
        labels['expressiveness'] = 'flat'
    else:
        labels['expressiveness'] = 'moderate'

    if centroid > 3000:
        labels['brightness'] = 'bright'
    elif centroid < 1800:
        labels['brightness'] = 'warm'
    else:
        labels['brightness'] = 'balanced'

    if cadence >= 1.8:
        labels['cadence'] = 'fast'
    elif cadence <= 0.8:
        labels['cadence'] = 'slow'
    else:
        labels['cadence'] = 'measured'

    if labels['volume_style'] == 'soft_spoken' and labels['cadence'] == 'slow':
        labels['primary_style'] = 'gentle'
    elif labels['volume_style'] == 'soft_spoken':
        labels['primary_style'] = 'soft_spoken'
    elif labels['volume_style'] == 'loud' and labels['cadence'] == 'fast':
        labels['primary_style'] = 'assertive'
    elif labels['volume_style'] == 'loud':
        labels['primary_style'] = 'loud'
    elif labels['cadence'] == 'fast':
        labels['primary_style'] = 'energetic'
    else:
        labels['primary_style'] = 'balanced'

    # Articulation: hesitancy ≠ long pauses alone (deliberate thinkers pause long
    # but speak clearly). True hesitancy = many short pauses + fillers + restarts.
    # Long calm pauses = deliberate. Transcript signals are most reliable when available.
    filler_rate = ts.get('filler_rate')       # None if no transcript
    restart_rate = ts.get('restart_rate', 0.0)
    if filler_rate is not None:
        # Transcript-guided (strongest signal)
        if filler_rate > 0.08 or restart_rate > 1.0:
            labels['articulation_level'] = 'hesitant'
        elif avg_pause_sec > 1.5 and filler_rate < 0.04:
            labels['articulation_level'] = 'deliberate'
        elif filler_rate < 0.02 and labels['cadence'] == 'fast':
            labels['articulation_level'] = 'articulate'
        elif labels['brightness'] == 'bright':
            labels['articulation_level'] = 'expressive'
        else:
            labels['articulation_level'] = 'measured'
    else:
        # Audio-only: many short meaningful pauses = hesitant;
        # few but long pauses = deliberate (Feynman-style thinking)
        many_short_pauses = pause_count >= 3 and avg_pause_sec < 0.9
        few_long_pauses = meaningful_pause_ratio > 0.15 and avg_pause_sec > 1.5
        if many_short_pauses:
            labels['articulation_level'] = 'hesitant'
        elif few_long_pauses:
            labels['articulation_level'] = 'deliberate'
        elif voiced_ratio > 0.60 and labels['cadence'] == 'fast':
            labels['articulation_level'] = 'articulate'
        elif labels['brightness'] == 'bright':
            labels['articulation_level'] = 'expressive'
        else:
            labels['articulation_level'] = 'measured'

    cal = calibration or {}
    n_prior = cal.get('n_prior_turns', 0)
    if n_prior >= 1:
        ecv_z = cal.get('energy_cv_zscore', 0)
        cadence_z = cal.get('segment_rate_zscore', 0)
        voiced_z = cal.get('voiced_ratio_zscore', 0)
        pause_z = cal.get('pause_ratio_zscore', 0)
        pitch_rng_z = cal.get('pitch_range_hz_zscore', 0)
        flux_z = cal.get('spectral_flux_zscore', 0)
        hesitancy_score = sum([
            pause_z > 0.7,
            cadence_z < -0.7,
            voiced_z < -0.7,
            pitch_variability > 0.45,
        ])
        elation_score = sum([
            ecv_z > 0.7,
            cadence_z > 0.7,
            voiced_z > 0.7,
            pitch_rng_z > 0.7,
            flux_z > 0.7,
        ])
    else:
        hesitancy_score = sum([
            pause_ratio > 0.40,
            cadence < 0.8,
            voiced_ratio < 0.38,
            pitch_variability > 0.45,
        ])
        elation_score = sum([
            energy_cv > 0.7,
            cadence >= 1.6,
            voiced_ratio > 0.65,
            pitch_range > 80,
            spectral_flux > 200,
        ])

    if elation_score >= 3 and elation_score > hesitancy_score:
        emotion_state = 'elated'
    elif elation_score == 2 and hesitancy_score < 2:
        emotion_state = 'enthusiastic'
    elif hesitancy_score >= 3:
        emotion_state = 'hesitant'
    elif hesitancy_score == 2:
        emotion_state = 'measured'
    elif elation_score == 0 and energy_cv < 0.25 and voiced_ratio < 0.5:
        emotion_state = 'low-energy'
    else:
        emotion_state = 'neutral'
    labels['emotion_state'] = emotion_state

    if labels['cadence'] == 'fast' and labels['volume_style'] != 'soft_spoken' and emotion_state in ('elated', 'enthusiastic'):
        talk_style = 'storyteller'
    elif labels['cadence'] == 'slow' and pause_ratio > 0.30:
        talk_style = 'deep-listener'
    elif labels['cadence'] == 'fast' and centroid > 2800:
        talk_style = 'quick-wit'
    elif emotion_state in ('hesitant', 'measured') and labels['brightness'] == 'warm':
        talk_style = 'earnest'
    else:
        talk_style = 'conversational'
    labels['talk_style'] = talk_style

    ei = 'Extraverted' if (labels['volume_style'] == 'loud' and cadence >= 1.5 and voiced_ratio > 0.6) else ('Introverted' if (labels['volume_style'] == 'soft_spoken' or voiced_ratio < 0.45) else 'Ambivert')
    ns = 'Intuitive' if (centroid > 2500 and pitch_variability > 0.20) else 'Grounded'
    tf = 'Feeling' if (labels['brightness'] == 'warm' and pause_ratio > 0.20) else ('Thinking' if (labels['brightness'] == 'bright' and cadence > 1.3) else 'Balanced')
    jp = 'Structured' if (labels['cadence'] == 'measured' and pause_ratio < 0.30) else ('Spontaneous' if (labels['cadence'] == 'fast' and spectral_flatness > 0.08) else 'Flexible')
    energy_label = {'elated': 'high-energy', 'enthusiastic': 'animated', 'hesitant': 'thoughtful', 'measured': 'deliberate', 'low-energy': 'low-key', 'neutral': 'steady'}[emotion_state]

    labels['mbti_like_traits'] = [ei, ns, tf, jp, energy_label]

    evaluation_tags = [labels['articulation_level'], emotion_state, talk_style]
    if labels['volume_style'] != 'moderate':
        evaluation_tags.append(labels['volume_style'])
    if labels['brightness'] != 'balanced':
        evaluation_tags.append(labels['brightness'])
    labels['evaluation_tags'] = evaluation_tags

    trait_descriptors = [labels['primary_style'], talk_style, emotion_state]
    labels['trait_descriptors'] = [d for d in trait_descriptors if d and d != 'neutral']

    compatibility_notes = {
        'elated': 'speaks with high energy and enthusiasm — pairs well with someone equally animated or who loves being energized',
        'enthusiastic': 'shows real excitement when engaged — compatibility shines with someone who matches their energy',
        'hesitant': 'takes time to open up — pairs beautifully with a patient, warm listener who creates safe space',
        'measured': 'speaks thoughtfully with intention — a great match for someone who values depth over speed',
        'low-energy': 'quiet and reserved in delivery — pairs well with someone equally calm or who draws people out gently',
        'neutral': 'even-keeled and composed — comfortable across a range of social energies',
    }
    labels['compatibility_note'] = compatibility_notes[emotion_state]

    return labels


def _analyze_audio_personality(features: dict, calibration: dict = None, transcript_signals: dict = None) -> dict:
    base_labels = _classify_audio_style_from_features(features, calibration, transcript_signals)
    try:
        system = (
            'You are a dating compatibility analyst. The user provided extracted audio feature metrics from a spoken response. '
            'Evaluate the speaker on volume, cadence, articulation, clarity, and emotional tone. '
            'Detect the speaker\'s emotional state (hesitant, measured, low-energy, neutral, enthusiastic, or elated) and their conversational talk_style (storyteller, deep-listener, quick-wit, earnest, or conversational). '
            'For articulation_level choose from: hesitant, measured, deliberate, expressive, articulate. '
            'deliberate = long thoughtful pauses but clear and direct when speaking (not the same as hesitant). '
            'hesitant = many fillers, restarts, or fragmented short bursts with uncertainty. '
            'Output only valid JSON with these keys: '
            'primary_style, secondary_style, articulation_level, emotion_state, talk_style, mbti_like_traits, evaluation_tags, trait_descriptors, compatibility_insight.'
        )
        heuristic_summary = {k: v for k, v in base_labels.items() if k != 'compatibility_note'}
        cal_section = ''
        if calibration and calibration.get('n_prior_turns', 0) >= 1:
            cal_display = {k: v for k, v in calibration.items() if not k.endswith('_baseline')}
            cal_section = (
                f"\nSession calibration (relative to this speaker's own prior turns):\n{json.dumps(cal_display, indent=2)}\n"
                "relative_energy/cadence/engagement show whether this response is above, at, or below this speaker's own baseline. "
                "Weight these relative signals heavily — they are more informative than absolute dB/Hz values alone.\n"
            )
        few_shot_examples = _find_nearest_labeled_examples(features)
        few_shot_text = ''
        if few_shot_examples:
            lines = []
            for i, (labels, f) in enumerate(few_shot_examples):
                key_feats = {k: f.get(k) for k in _SIM_KEYS}
                lines.append(f"Example {i+1}: features={json.dumps(key_feats)} → human_labels={json.dumps(labels)}")
            few_shot_text = "Manually labeled reference examples (treat as ground truth for calibration):\n" + "\n".join(lines) + "\n\n"
        prompt = few_shot_text + (
            f"Raw audio features:\n{json.dumps(features, indent=2)}\n"
            f"{cal_section}\n"
            f"Heuristic pre-analysis (calibrated anchors):\n{json.dumps(heuristic_summary, indent=2)}\n\n"
            'The heuristic labels use relative z-scores when session history is available, making them reliable. '
            'Use them as your primary anchor — refine only where raw numbers clearly contradict. '
            'Do NOT upgrade emotion_state to enthusiastic or elated unless relative_energy is above_baseline AND cadence is faster_than_usual. '
            'Do NOT give unearned positive framing for low-energy or hesitant speakers. '
            'Be accurate: if the speaker sounds flat or reserved relative to their own baseline, say so in compatibility_insight. '
            'Choose a concise primary_style from: soft_spoken, gentle, loud, assertive, reserved, energetic, thoughtful, warm. '
            'Provide secondary_style, articulation_level, emotion_state (hesitant, measured, low-energy, neutral, enthusiastic, or elated), '
            'talk_style (storyteller, deep-listener, quick-wit, earnest, or conversational), and mbti_like_traits as a list of 4-5 MBTI-axis descriptors. '
            'Output only valid JSON with these keys: primary_style, secondary_style, articulation_level, emotion_state, talk_style, mbti_like_traits, evaluation_tags, trait_descriptors, compatibility_insight. '
            'Return only valid JSON and do not include any markdown or additional explanation.'
        )
        AI_result = call_k2_with_fallback(system, prompt)
        if isinstance(AI_result, dict):
            AI_result['source'] = 'k2'
            AI_result['heuristic'] = base_labels
            if calibration:
                AI_result['calibration'] = calibration
            return AI_result
    except Exception as err:
        print(f"[AUDIO] K2 personality classification failed: {err}")

    return {
        'source': 'heuristic',
        'primary_style': base_labels.get('primary_style', 'balanced'),
        'secondary_style': base_labels.get('brightness', 'balanced'),
        'emotion_state': base_labels.get('emotion_state', 'neutral'),
        'talk_style': base_labels.get('talk_style', 'conversational'),
        'trait_descriptors': base_labels.get('trait_descriptors', []),
        'compatibility_insight': base_labels.get('compatibility_note', ''),
        'heuristic': base_labels,
        'calibration': calibration or {},
    }


def _build_signal_note(audio_insights: dict) -> str:
    ap = audio_insights.get('audio_personality', {})
    ts = audio_insights.get('transcript_signals', {})
    cal = ap.get('calibration', {}) if ap else {}

    parts = []

    emotion = ap.get('emotion_state')
    if emotion:
        rel = cal.get('relative_energy', '')
        parts.append(f"emotion={emotion}" + (f"({rel})" if rel and rel != 'at_baseline' else ''))

    talk = ap.get('talk_style')
    if talk:
        parts.append(f"talk_style={talk}")

    style = ap.get('primary_style')
    if style:
        parts.append(f"vocal={style}")

    rel_cadence = cal.get('relative_cadence', '')
    if rel_cadence and rel_cadence != 'typical':
        parts.append(f"pacing={rel_cadence}")

    if ts:
        if ts.get('question_count', 0) > 0:
            parts.append(f"asked {ts['question_count']}q")
        if ts.get('filler_rate', 0) > 0.07:
            parts.append('high-fillers')
        if ts.get('hedge_ratio', 0) > 0.06:
            parts.append('hedging')
        rc = ts.get('response_category')
        if rc in ('brief', 'elaborate'):
            parts.append(rc)
        if ts.get('vocab_diversity', 0) > 0.82:
            parts.append('rich-vocab')

    if not parts:
        return ''

    instructions = (
        "If hesitant/measured: slow down, be warm, give space. "
        "If elated/enthusiastic: match their energy. "
        "If they asked questions: answer before redirecting. "
        "If brief: short warm prompt; if elaborate: acknowledge their depth."
    )
    return f"[SIGNALS: {' | '.join(parts)}]\n{instructions}\n\n"


async def _transcribe_and_update_db(audio_bytes: bytes, browser_transcript: str, session_id: str, turn: int) -> None:
    """Background: re-transcribe with fillers and update the stored labels."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        rich = await loop.run_in_executor(None, lambda: _transcribe_with_fillers(audio_bytes, fallback=browser_transcript))
        if rich and rich != browser_transcript:
            rich_signals = _extract_transcript_signals(rich)
            filler_rate = rich_signals.get('filler_rate', 0.0)
            filler_presence = 'high' if filler_rate > 0.10 else ('moderate' if filler_rate > 0.05 else ('low' if filler_rate > 0.01 else 'none'))
            conn = _get_db_conn()
            row = conn.execute(
                "SELECT auto_labels_json FROM audio_labels WHERE session_id = ? AND turn = ?",
                (session_id, turn),
            ).fetchone()
            if row:
                labels = json.loads(row['auto_labels_json'])
                labels['filler_presence'] = filler_presence
                labels['rich_transcript'] = rich
                conn.execute(
                    "UPDATE audio_labels SET auto_labels_json = ? WHERE session_id = ? AND turn = ?",
                    (json.dumps(labels), session_id, turn),
                )
                conn.commit()
            conn.close()
    except Exception as e:
        print(f"[TRANSCRIBE] Background filler update failed: {e}")


async def _analyze_personality_background(session_id: str, raw_features: dict, calibration: dict, db_turn: int = None, transcript_signals: dict = None) -> None:
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        personality = await loop.run_in_executor(None, lambda: _analyze_audio_personality(raw_features, calibration, transcript_signals))
        current = session_audio_insights.get(session_id, {})
        current['audio_personality'] = personality
        session_audio_insights[session_id] = current
        # Persist K2 results back to audio_labels so labeling studio shows LLM output
        if db_turn is not None:
            try:
                conn = _get_db_conn()
                conn.execute(
                    "UPDATE audio_labels SET auto_labels_json = ? WHERE session_id = ? AND turn = ?",
                    (json.dumps(personality), session_id, db_turn),
                )
                conn.commit()
                conn.close()
            except Exception as db_err:
                print(f"[AUDIO] Failed to persist K2 auto_labels to DB: {db_err}")
    except Exception as e:
        print(f"[AUDIO] Background personality analysis failed: {e}")


_SIM_KEYS = ['energy_cv', 'segment_rate', 'voiced_ratio', 'pause_ratio', 'pitch_std_hz', 'spectral_flux']
_SIM_RANGES = {'energy_cv': 1.0, 'segment_rate': 3.0, 'voiced_ratio': 1.0, 'pause_ratio': 1.0, 'pitch_std_hz': 60.0, 'spectral_flux': 400.0}

def _find_nearest_labeled_examples(features: dict, n: int = 3) -> list:
    conn = _get_db_conn()
    rows = conn.execute(
        "SELECT features_json, human_labels_json FROM audio_labels WHERE human_labels_json IS NOT NULL"
    ).fetchall()
    conn.close()
    if not rows:
        return []
    def dist(f1, f2):
        return sum(((f1.get(k, 0) - f2.get(k, 0)) / _SIM_RANGES.get(k, 1)) ** 2 for k in _SIM_KEYS) ** 0.5
    candidates = []
    for row in rows:
        try:
            f = json.loads(row['features_json'])
            labels = json.loads(row['human_labels_json'])
            candidates.append((dist(features, f), labels, f))
        except Exception:
            continue
    candidates.sort(key=lambda x: x[0])
    return [(labels, f) for _, labels, f in candidates[:n]]


def _build_interview_prompt(session_id: str, audio_insights: Optional[dict] = None) -> str:
    system_prompt = INTERVIEWER_SYSTEM
    user_turns = sum(1 for msg in sessions_db[session_id] if msg['role'] == 'user')
    if user_turns >= 12:
        system_prompt += "\n\n[SYSTEM: This is near the end. Gracefully close the conversation soon.]"

    history_text = "\n".join(
        f"{('User' if msg['role'] == 'user' else 'Assistant')}: {msg['content']}"
        for msg in sessions_db[session_id]
    )

    signal_note = _build_signal_note(audio_insights) if audio_insights else ''

    return (
        f"{system_prompt}\n\n"
        "Return ONLY the next assistant message and prefix it exactly with FINAL_RESPONSE:.\n"
        "Do not include rules, analysis, options, or any user text.\n\n"
        f"{signal_note}{history_text}\n"
        "Assistant:"
    )


def _hash_password(password: str, salt: Optional[str] = None) -> str:
    actual_salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), actual_salt.encode("utf-8"), 120000)
    return f"{actual_salt}${digest.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    return _hash_password(password, salt).split("$", 1)[1] == digest


def _create_auth_token(user_id: int, ttl_seconds: int = 60 * 60 * 24 * 7) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = int(time.time()) + ttl_seconds
    conn = _get_db_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO auth_tokens (token, user_id, expires_at) VALUES (?, ?, ?)",
        (token, user_id, expires_at),
    )
    conn.commit()
    conn.close()
    return token


def _password_reset_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _create_password_reset_token(user_id: int, ttl_seconds: int = 60 * 30) -> str:
    token = secrets.token_urlsafe(48)
    token_hash = _password_reset_token_hash(token)
    now = int(time.time())
    expires_at = now + ttl_seconds

    conn = _get_db_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM password_reset_tokens WHERE user_id = ?", (user_id,))
    cur.execute(
        """
        INSERT INTO password_reset_tokens (token_hash, user_id, expires_at, used_at, created_at)
        VALUES (?, ?, ?, NULL, ?)
        """,
        (token_hash, user_id, expires_at, now),
    )
    conn.commit()
    conn.close()
    return token


def _consume_password_reset_token(token: str) -> Optional[int]:
    token_hash = _password_reset_token_hash(token)
    now = int(time.time())

    conn = _get_db_conn()
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT user_id, expires_at, used_at
        FROM password_reset_tokens
        WHERE token_hash = ?
        """,
        (token_hash,),
    ).fetchone()

    if not row or row["used_at"] is not None or row["expires_at"] <= now:
        conn.close()
        return None

    cur.execute(
        "UPDATE password_reset_tokens SET used_at = ? WHERE token_hash = ?",
        (now, token_hash),
    )
    conn.commit()
    conn.close()
    return row["user_id"]


def _send_password_reset_email(email: str, token: str) -> bool:
    reset_link = f"{FRONTEND_URL.rstrip('/')}/auth?mode=reset&token={token}"
    subject = "Reset your Wavelength password"
    body = (
        "We got a request to reset your Wavelength password.\n\n"
        f"Use this secure link (valid for 30 minutes):\n{reset_link}\n\n"
        "If you did not request this, you can ignore this email."
    )

    if not SMTP_HOST or not SMTP_USER or not SMTP_PASS:
        print(f"[Auth] SMTP not configured. Password reset link for {email}: {reset_link}")
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM
    msg["To"] = email
    msg.set_content(body)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            if SMTP_USE_TLS:
                server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        return True
    except Exception as exc:
        print(f"[Auth] Failed to send password reset email: {exc}")
        print(f"[Auth] Password reset link for {email}: {reset_link}")
        return False


def _get_authenticated_user(authorization: Optional[str]) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    token = authorization.split(" ", 1)[1].strip()
    now = int(time.time())

    conn = _get_db_conn()
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT u.id, u.email, u.display_name
        FROM auth_tokens t
        JOIN auth_users u ON u.id = t.user_id
        WHERE t.token = ? AND t.expires_at > ?
        """,
        (token, now),
    ).fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return {"id": row["id"], "email": row["email"], "display_name": row["display_name"]}

# ============================================================================
# SYSTEM PROMPTS
# ============================================================================

INTERVIEWER_SYSTEM = """You are wavelength's warm, perceptive interviewer. Have a genuine, casual conversation
that reveals who the interviewee really is and who they connect best with.

Wavelength is a friend-finder that helps people discover meaningful platonic connections by default.
If the user brings up wanting a romantic partner on their own, naturally
shift to exploring that too (orientation, preferences, what they need in a partner).

Primary goal:
- Understand what kind of connection they're looking for (friends, community, or if they mention it, a partner).
- Understand what they value in people they're close to.
- Understand their own personality, social style, and emotional needs.
- Understand their interests, lifestyle, and how they like to spend time with others.

Interview flow (soft, conversational):
- Early (turns 1-2): set them at ease and invite them to paint a picture of their world — who they spend time with, what their days look like, what brought them here.
- Middle (turns 3-4): go deeper on values, a specific memory or story about a friendship that shaped them, how they navigate conflict or tough conversations, what genuinely lights them up in a conversation or shared experience.
- Identity/personality throughout (turns 5-6): their sense of humor, how they decompress, what they nerd out about, the texture of how they like to spend time with people.
- Late (turns 7): reflect something real you noticed about them and close warmly.

Question style — this is critical:
- NEVER ask a yes/no or closed question. Every question must invite a story, opinion, memory, or description.
- Always use open frames: "What does X look like for you?", "Tell me about a time when…", "How do you usually feel when…", "Walk me through…", "What's your take on…", "Describe the last time you…"
- BAD: "Do you like big groups?" → GOOD: "What's your energy like at a party where you barely know anyone?"
- BAD: "Are you close with your friends?" → GOOD: "Tell me about a friendship that has genuinely shaped who you are."
- BAD: "Do you value honesty?" → GOOD: "What does it look like when someone earns your trust?"
- BAD: "Are you introverted?" → GOOD: "What does a perfect weekend actually look like for you?"
- When someone gives a short answer, don't move on — ask them to take you further into it: "What was that like?", "Say more about that.", "What do you think that's about?"

Rules:
- Ask one question at a time.
- Keep responses at a medium length (1-3 sentences + the question). Don't over-explain before asking.
- Reflect something specific from what they said before asking — mirror their language, not a generic paraphrase.
- Empathize with them and build rapport; match their energy and register.
- If they seem closed off, make a light, genuine observation and try a completely different angle.
- If they show real energy on something, follow that thread deeper before moving on.
- Be inclusive, non-judgmental, and let them skip any sensitive question.
- Adopt a similar communication style to theirs as the conversation progresses (more formal vs slang, more or less emotive, CAPS, etc).
- Never mention you are an AI or that this is an interview."""

EXTRACTION_SYSTEM = """You are a wavelengthlity analyst. Given a conversation transcript, extract a structured
wavelengthlity profile. Output ONLY valid JSON, no markdown, no preamble.

Schema:
{
  "traits": {
    "openness": 0.0-1.0,
    "conscientiousness": 0.0-1.0,
    "extraversion": 0.0-1.0,
    "agreeableness": 0.0-1.0,
    "emotional_stability": 0.0-1.0,
    "novelty_seeking": 0.0-1.0,
    "security_need": 0.0-1.0
  },
  "conflict_style": "avoidant|direct|collaborative|passive",
  "communication_register": "formal|casual|mixed",
  "reasoning_style": "emotional|analytical|balanced",
  "values": ["3-6 core values as short phrases"],
  "interests": ["3-6 genuine interests"],
  "worldview": "2-3 sentence synthesis of how this person sees life",
  "energy_topics": ["topics where they showed most engagement"],
  "deflection_topics": ["topics they avoided or answered briefly"],
  "humor_style": "dry|playful|sarcastic|earnest|observational",
  "talk_style": "storyteller|listener|quick-wit|deep-diver|teaser|riffing",
  "social_energy": "introvert-leaning|extrovert-leaning|ambivert",
  "fun_mode": "adventure|cozy|social|creative|intellectual",
  "summary": "1 sentence warm portrait of who this person is"
}

Infer humor_style from how they joke or deflect. Infer talk_style from whether they elaborate, ask back, tell stories, or give short answers. Infer social_energy from references to crowds, alone time, and their energy description. Infer fun_mode from what activities and topics excite them most."""

COMPATIBILITY_SYSTEM = """You are a compatibility analyst with deep expertise in relationship psychology.
You receive two wavelengthlity profiles and must reason step by step through compatibility.

Think through:
1. Where their values genuinely align (beneath surface vocabulary differences)
2. Complementary traits (differences that strengthen, not clash)
3. Genuine friction points and how they might manifest
4. Communication style compatibility
5. Conversational chemistry — do they have compatible talk styles, matching social energy, and overlapping fun modes? Would they have fun just talking?

Output ONLY valid JSON:
{
  "overall_score": 0.0-1.0,
  "dimensions": {
    "values_alignment": 0.0-1.0,
    "communication_compatibility": 0.0-1.0,
    "lifestyle_fit": 0.0-1.0,
    "emotional_compatibility": 0.0-1.0,
    "intellectual_connection": 0.0-1.0,
    "growth_potential": 0.0-1.0,
    "conversational_chemistry": 0.0-1.0
  },
  "strengths": ["2-3 specific reasons this pairing works"],
  "friction_points": ["1-2 honest friction points to navigate"],
  "reasoning": "3-4 sentences referencing actual traits from both profiles",
  "conversation_starter": "One specific topic that would light both of them up"
}"""

SIMULATION_SYSTEM = """Simulate how two people with these wavelengthlity profiles would talk on a first date.
Write a short realistic dialogue (6-8 exchanges). Show wavelengthlity through HOW they
talk — vocabulary, who asks questions, who tells stories. Output ONLY valid JSON:
{
  "topic": "the topic discussed",
  "dialogue": [{"speaker": "Name", "line": "what they say"}, ...],
  "insight": "1-2 sentences on what this reveals about their dynamic"
}"""

# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class CreateProfileRequest(BaseModel):
    user_id: str
    name: str
    age: Optional[int] = None
    gender: Optional[str] = None
    photo_url: Optional[str] = None
    preferred_age_min: Optional[int] = None
    preferred_age_max: Optional[int] = None

class StartSessionRequest(BaseModel):
    user_id: str
    name: str

class ChatRequest(BaseModel):
    session_id: str
    message: str


class InterviewExtractTurn(BaseModel):
    role: str
    content: str


class InterviewExtractRequest(BaseModel):
    user_id: str
    session_id: Optional[str] = None
    name: Optional[str] = None
    transcript: Optional[list[InterviewExtractTurn]] = None


class TTSRequest(BaseModel):
    text: str
    voice_id: Optional[str] = None

class CompatibilityRequest(BaseModel):
    user_id_a: str
    user_id_b: str

class SimulationRequest(BaseModel):
    user_id_a: str
    user_id_b: str

class DirectMessageRequest(BaseModel):
    from_user_id: str
    to_user_id: str
    content: str


class MeetupFeedbackRequest(BaseModel):
    from_user_id: str
    to_user_id: str
    met: bool
    chemistry_rating: Optional[int] = None
    communication_rating: Optional[int] = None
    safety_rating: Optional[int] = None
    would_meet_again: Optional[bool] = None
    notes: Optional[str] = None


class AIChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str


class RegisterRequest(BaseModel):
    email: str
    password: str
    display_name: Optional[str] = None


class LoginRequest(BaseModel):
    email: str
    password: str


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

# ============================================================================
# K2 HELPER FUNCTIONS
# ============================================================================

def call_k2(system: str, prompt: str, retries: int = 2) -> str:
    """Call K2 Think V2 and return assistant content with light retry on transient failures."""
    if not K2_API_KEY:
        raise ValueError("K2_API_KEY not set")
    headers = {
        "Authorization": f"Bearer {K2_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "MBZUAI-IFM/K2-Think-v2",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 8000,
        "temperature": 0.3,
    }
    last_err = None
    for attempt in range(retries + 1):
        try:
            r = httpx.post(
                f"{K2_BASE_URL}/chat/completions",
                json=payload,
                headers=headers,
                timeout=120,
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except (httpx.TimeoutException, httpx.RequestError, httpx.HTTPStatusError) as e:
            last_err = e
            should_retry = False
            if isinstance(e, (httpx.TimeoutException, httpx.RequestError)):
                should_retry = True
            elif isinstance(e, httpx.HTTPStatusError):
                code = e.response.status_code
                should_retry = code in {408, 409, 425, 429, 500, 502, 503, 504}

            if not should_retry or attempt >= retries:
                break

            backoff_seconds = 0.6 * (attempt + 1)
            time.sleep(backoff_seconds)

    raise ValueError(f"K2 request failed after retries: {last_err}")

def call_k2_with_fallback(system: str, prompt: str) -> dict:
    """Try K2, always return parsed dict. K2 is required for reasoning."""
    raw = ""
    try:
        raw = call_k2(system, prompt)
    except Exception as e:
        print(f"K2 unavailable ({e}), but K2 is required for reasoning tasks")
        raise ValueError(f"K2 API is required for reasoning. Error: {e}")

    # K2 Think outputs reasoning before the final JSON answer.
    # Strip <think>...</think> blocks, then find the last top-level JSON object.
    raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    # Try each '{' from the end until we get valid JSON (handles reasoning prefix)
    for i in range(len(raw) - 1, -1, -1):
        if raw[i] == '{':
            end = raw.rfind("}", i) + 1
            if end > i:
                try:
                    return json.loads(raw[i:end])
                except json.JSONDecodeError:
                    continue
    raise ValueError(f"Could not extract JSON from K2 response. Response starts with: {raw[:300]!r}")


def extract_text_response(response) -> str:
    """Extract text from a Gemini SDK response object safely."""
    if response is None:
        return ""

    try:
        text = response.text
        if isinstance(text, str) and text.strip():
            return text
    except (ValueError, AttributeError):
        pass

    candidates = getattr(response, "candidates", None) or []
    parts = []
    for cand in candidates:
        content = getattr(cand, "content", None)
        for part in getattr(content, "parts", None) or []:
            part_text = getattr(part, "text", None)
            if isinstance(part_text, str) and part_text:
                parts.append(part_text)
    return "\n".join(parts).strip()


def extract_assistant_reply(raw_text: str) -> str:
    """Return only the assistant's final message from a potentially noisy response."""
    text = re.sub(r'<think>.*?</think>', '', (raw_text or ''), flags=re.DOTALL).strip()
    text = re.sub(r'</?think>', '', text, flags=re.IGNORECASE).strip()

    # Prefer explicit marker when the model follows instructions.
    if "FINAL_RESPONSE:" in text:
        text = text.rsplit("FINAL_RESPONSE:", 1)[-1].strip()
    elif "Assistant:" in text:
        text = text.rsplit("Assistant:", 1)[-1].strip()

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    blocked_prefixes = (
        "user:",
        "assistant:",
        "system:",
        "rules:",
        "you are ",
        "return only",
        "- ",
        "* ",
    )
    kept = [ln for ln in lines if not ln.lower().startswith(blocked_prefixes)]

    # Use only the final conversational line to avoid duplicated echoes.
    candidate = kept[-1].strip() if kept else text

    # Remove occasional echoed kickoff user text.
    candidate = re.sub(
        r'^\s*[A-Za-z][A-Za-z0-9 _-]{0,25}[:\-]?\s*["\']?Hi,\s*I[\'’]?m[^"\']*["\']?\s*',
        "",
        candidate,
        flags=re.IGNORECASE,
    ).strip()

    # Remove common wrapper prefixes generated by some model completions.
    candidate = re.sub(r'^\s*(thus\s+output|output|final\s+response)\s*[:\-]\s*', '', candidate, flags=re.IGNORECASE).strip()

    return candidate[:500].strip()


TRAIT_KEYS = [
    "openness",
    "conscientiousness",
    "extraversion",
    "agreeableness",
    "emotional_stability",
    "novelty_seeking",
    "security_need",
]


def _to_set(values) -> set:
    if not isinstance(values, list):
        return set()
    return {str(v).strip().lower() for v in values if str(v).strip()}


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def _safe_trait(traits: dict, key: str) -> float:
    if not isinstance(traits, dict):
        return 0.5
    try:
        val = float(traits.get(key, 0.5))
    except Exception:
        return 0.5
    return max(0.0, min(1.0, val))


def _age_preference_score(preference_owner: dict, other_profile: dict) -> float:
    preferred_min = preference_owner.get("preferred_age_min")
    preferred_max = preference_owner.get("preferred_age_max")
    other_age = other_profile.get("age")

    if other_age is None or (preferred_min is None and preferred_max is None):
        return 1.0

    if preferred_min is not None and other_age < preferred_min:
        distance = preferred_min - other_age
    elif preferred_max is not None and other_age > preferred_max:
        distance = other_age - preferred_max
    else:
        return 1.0

    if distance <= 2:
        return 0.85
    if distance <= 5:
        return 0.65
    if distance <= 8:
        return 0.45
    return 0.25


def _age_within_preference(preference_owner: dict, other_profile: dict) -> bool:
    preferred_min = preference_owner.get("preferred_age_min")
    preferred_max = preference_owner.get("preferred_age_max")
    other_age = other_profile.get("age")

    if other_age is None or (preferred_min is None and preferred_max is None):
        return True
    if preferred_min is not None and other_age < preferred_min:
        return False
    if preferred_max is not None and other_age > preferred_max:
        return False
    return True


def compute_profile_match(profile_a: dict, profile_b: dict) -> dict:
    wa = profile_a.get("wavelengthlity") or {}
    wb = profile_b.get("wavelengthlity") or {}
    ta = wa.get("traits") or {}
    tb = wb.get("traits") or {}

    trait_sims = []
    for key in TRAIT_KEYS:
        trait_sims.append(1.0 - abs(_safe_trait(ta, key) - _safe_trait(tb, key)))
    trait_similarity = sum(trait_sims) / len(TRAIT_KEYS)

    values_similarity = _jaccard(_to_set(wa.get("values")), _to_set(wb.get("values")))
    interests_similarity = _jaccard(_to_set(wa.get("interests")), _to_set(wb.get("interests")))
    energy_similarity = _jaccard(_to_set(wa.get("energy_topics")), _to_set(wb.get("energy_topics")))

    values_alignment = (values_similarity * 0.6) + (interests_similarity * 0.25) + (energy_similarity * 0.15)

    communication_parts = []
    communication_parts.append(1.0 if wa.get("communication_register") == wb.get("communication_register") else 0.4)
    communication_parts.append(1.0 if wa.get("conflict_style") == wb.get("conflict_style") else 0.45)
    communication_parts.append(1.0 if wa.get("reasoning_style") == wb.get("reasoning_style") else 0.5)
    communication_compatibility = sum(communication_parts) / len(communication_parts)

    talk_style_a = (wa.get("talk_style") or "").strip().lower()
    talk_style_b = (wb.get("talk_style") or "").strip().lower()
    social_energy_a = (wa.get("social_energy") or "").strip().lower()
    social_energy_b = (wb.get("social_energy") or "").strip().lower()
    fun_mode_a = (wa.get("fun_mode") or "").strip().lower()
    fun_mode_b = (wb.get("fun_mode") or "").strip().lower()

    COMPLEMENTARY_TALK = {("storyteller", "listener"), ("listener", "storyteller"), ("quick-wit", "riffing"), ("riffing", "quick-wit"), ("deep-diver", "listener"), ("listener", "deep-diver")}
    SAME_TALK_PENALTY = {"storyteller", "quick-wit"}
    if (talk_style_a, talk_style_b) in COMPLEMENTARY_TALK:
        talk_style_score = 1.0
    elif talk_style_a == talk_style_b and talk_style_a in SAME_TALK_PENALTY:
        talk_style_score = 0.45
    elif talk_style_a == talk_style_b:
        talk_style_score = 0.75
    elif talk_style_a and talk_style_b:
        talk_style_score = 0.55
    else:
        talk_style_score = 0.5

    if not social_energy_a or not social_energy_b:
        social_energy_score = 0.5
    elif social_energy_a == social_energy_b:
        social_energy_score = 1.0
    elif "ambivert" in (social_energy_a, social_energy_b):
        social_energy_score = 0.75
    else:
        social_energy_score = 0.4

    FUN_ADJACENCY = {
        "adventure": {"social", "creative"},
        "cozy": {"intellectual", "creative"},
        "social": {"adventure", "creative"},
        "creative": {"intellectual", "cozy", "social", "adventure"},
        "intellectual": {"cozy", "creative"},
    }
    if not fun_mode_a or not fun_mode_b:
        fun_mode_score = 0.5
    elif fun_mode_a == fun_mode_b:
        fun_mode_score = 1.0
    elif fun_mode_b in FUN_ADJACENCY.get(fun_mode_a, set()):
        fun_mode_score = 0.7
    else:
        fun_mode_score = 0.3

    conversational_chemistry = (
        energy_similarity * 0.35
        + talk_style_score * 0.30
        + social_energy_score * 0.20
        + fun_mode_score * 0.15
    )

    lifestyle_fit = (
        (1.0 - abs(_safe_trait(ta, "novelty_seeking") - _safe_trait(tb, "novelty_seeking"))) * 0.5
        + (1.0 - abs(_safe_trait(ta, "security_need") - _safe_trait(tb, "security_need"))) * 0.5
    )

    emotional_compatibility = (
        (1.0 - abs(_safe_trait(ta, "agreeableness") - _safe_trait(tb, "agreeableness"))) * 0.5
        + (1.0 - abs(_safe_trait(ta, "emotional_stability") - _safe_trait(tb, "emotional_stability"))) * 0.5
    )

    intellectual_connection = (
        (1.0 - abs(_safe_trait(ta, "openness") - _safe_trait(tb, "openness"))) * 0.6
        + values_similarity * 0.4
    )

    growth_potential = 1.0 - abs(trait_similarity - 0.7)
    age_preference_fit = (
        _age_preference_score(profile_a, profile_b) + _age_preference_score(profile_b, profile_a)
    ) / 2

    dimensions = {
        "conversational_chemistry": max(0.0, min(1.0, conversational_chemistry)),
        "values_alignment": max(0.0, min(1.0, values_alignment)),
        "communication_compatibility": max(0.0, min(1.0, communication_compatibility)),
        "lifestyle_fit": max(0.0, min(1.0, lifestyle_fit)),
        "emotional_compatibility": max(0.0, min(1.0, emotional_compatibility)),
        "intellectual_connection": max(0.0, min(1.0, intellectual_connection)),
        "growth_potential": max(0.0, min(1.0, growth_potential)),
        "age_preference_fit": max(0.0, min(1.0, age_preference_fit)),
    }

    overall_score = (
        dimensions["conversational_chemistry"] * 0.23
        + dimensions["values_alignment"] * 0.18
        + dimensions["communication_compatibility"] * 0.15
        + dimensions["lifestyle_fit"] * 0.12
        + dimensions["emotional_compatibility"] * 0.12
        + dimensions["intellectual_connection"] * 0.12
        + dimensions["growth_potential"] * 0.05
        + dimensions["age_preference_fit"] * 0.03
    )

    common_values = list(_to_set(wa.get("values")) & _to_set(wb.get("values")))[:3]
    common_interests = list(_to_set(wa.get("interests")) & _to_set(wb.get("interests")))[:3]
    common_topics = list(_to_set(wa.get("energy_topics")) & _to_set(wb.get("energy_topics")))[:2]
    commonalities = common_values + common_interests + common_topics

    return {
        "overall_score": max(0.0, min(1.0, overall_score)),
        "dimensions": dimensions,
        "commonalities": commonalities,
    }


def remove_duplicate_users() -> int:
    """Remove duplicate profiles by normalized name + photo URL."""
    seen = {}
    duplicate_ids = []

    for user_id, profile in users_db.items():
        name = (profile.get("name") or "").strip().lower()
        photo_url = (profile.get("photo_url") or "").strip().lower()
        if not name or not photo_url:
            continue

        key = (name, photo_url)
        if key in seen:
            duplicate_ids.append(user_id)
        else:
            seen[key] = user_id

    for user_id in duplicate_ids:
        users_db.pop(user_id, None)

    return len(duplicate_ids)

# ============================================================================
# ROUTES
# ============================================================================

@app.get("/health")
def health():
    """Health check endpoint."""
    return {"status": "ok"}


@app.on_event("startup")
def preload_demo_users():
    """Initialize DB, hydrate memory, and ensure demo users exist."""
    init_db()
    os.makedirs("audio_samples", exist_ok=True)
    _load_profiles_from_db()
    _load_unmatches_from_db()

    if not users_db:
        seed_demo_users()

    # Remove legacy test user if present
    if "test-user-001" in users_db:
        del users_db["test-user-001"]
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.execute("DELETE FROM profiles WHERE user_id = 'test-user-001'")
            conn.commit()
            conn.close()
        except Exception:
            pass

    removed = remove_duplicate_users()
    if removed > 0:
        _sync_profiles_to_db()

@app.post("/profile/create")
def create_profile(req: CreateProfileRequest):
    """Create a new user profile."""
    preferred_age_min = req.preferred_age_min
    preferred_age_max = req.preferred_age_max

    if preferred_age_min is not None and not 18 <= preferred_age_min <= 120:
        raise HTTPException(status_code=400, detail="preferred_age_min must be between 18 and 120")
    if preferred_age_max is not None and not 18 <= preferred_age_max <= 120:
        raise HTTPException(status_code=400, detail="preferred_age_max must be between 18 and 120")
    if preferred_age_min is not None and preferred_age_max is not None and preferred_age_min > preferred_age_max:
        raise HTTPException(status_code=400, detail="preferred_age_min cannot be greater than preferred_age_max")

    profile = {
        "user_id": req.user_id,
        "name": req.name,
        "age": req.age,
        "gender": req.gender,
        "photo_url": req.photo_url or f"https://i.pravatar.cc/300?img=1",
        "wavelengthlity": None,
        "preferred_age_min": preferred_age_min,
        "preferred_age_max": preferred_age_max,
    }
    users_db[req.user_id] = profile
    _db_upsert_profile(profile)
    return profile


@app.post("/auth/register")
def auth_register(req: RegisterRequest):
    """Register a real account using email/password and return an access token."""
    email = (req.email or "").strip().lower()
    password = req.password or ""
    display_name = (req.display_name or "").strip() or None

    if "@" not in email or "." not in email:
        raise HTTPException(status_code=400, detail="Please provide a valid email")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    conn = _get_db_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO auth_users (email, password_hash, display_name, created_at) VALUES (?, ?, ?, ?)",
            (email, _hash_password(password), display_name, datetime.utcnow().isoformat() + "Z"),
        )
        user_id = cur.lastrowid
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=409, detail="Email already registered")

    conn.close()
    token = _create_auth_token(user_id)
    return {
        "token": token,
        "user": {
            "id": user_id,
            "email": email,
            "display_name": display_name,
        },
    }


@app.post("/auth/login")
def auth_login(req: LoginRequest):
    """Log in an existing account and return an access token."""
    email = (req.email or "").strip().lower()
    password = req.password or ""

    conn = _get_db_conn()
    cur = conn.cursor()
    row = cur.execute(
        "SELECT id, email, display_name, password_hash FROM auth_users WHERE email = ?",
        (email,),
    ).fetchone()
    conn.close()

    if not row or not _verify_password(password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = _create_auth_token(row["id"])
    return {
        "token": token,
        "user": {
            "id": row["id"],
            "email": row["email"],
            "display_name": row["display_name"],
        },
    }


@app.get("/auth/me")
def auth_me(Authorization: Optional[str] = Header(default=None)):
    """Resolve the current user from a Bearer token."""
    user = _get_authenticated_user(Authorization)
    return {"user": user}


@app.post("/auth/forgot-password")
def auth_forgot_password(req: ForgotPasswordRequest):
    """Request password reset and send verification link to email."""
    email = (req.email or "").strip().lower()

    # Avoid account enumeration: always return the same success response.
    if not email or "@" not in email or "." not in email:
        return {"ok": True, "message": "If this email exists, a password reset link has been sent."}

    conn = _get_db_conn()
    cur = conn.cursor()
    row = cur.execute("SELECT id, email FROM auth_users WHERE email = ?", (email,)).fetchone()
    conn.close()

    if row:
        token = _create_password_reset_token(row["id"])
        _send_password_reset_email(row["email"], token)

    return {"ok": True, "message": "If this email exists, a password reset link has been sent."}


@app.post("/auth/reset-password")
def auth_reset_password(req: ResetPasswordRequest):
    """Reset password using a valid email verification token."""
    token = (req.token or "").strip()
    new_password = req.new_password or ""

    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    if not token:
        raise HTTPException(status_code=400, detail="Missing reset token")

    user_id = _consume_password_reset_token(token)
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    conn = _get_db_conn()
    cur = conn.cursor()
    cur.execute("UPDATE auth_users SET password_hash = ? WHERE id = ?", (_hash_password(new_password), user_id))
    # Revoke active sessions after password change.
    cur.execute("DELETE FROM auth_tokens WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

    return {"ok": True, "message": "Password updated successfully. Please log in."}

@app.post("/api/text-to-speech")
async def text_to_speech(request: TTSRequest):
    """Convert text to speech using ElevenLabs."""
    if not elevenlabs_client:
        raise HTTPException(status_code=503, detail="ElevenLabs not configured (missing ELEVENLABS_API_KEY)")
    
    try:
        audio_generator = elevenlabs_client.text_to_speech.convert(
            text=request.text,
            voice_id=request.voice_id or ELEVENLABS_VOICE_ID,
            model_id="eleven_multilingual_v2",
            voice_settings=VoiceSettings(
                stability=0.3,
                similarity_boost=0.75,
                style=0.5,
                use_speaker_boost=True
            )
        )
        
        # Convert generator to bytes
        audio_bytes = b"".join(audio_generator)
        
        return Response(
            content=audio_bytes,
            media_type="audio/mpeg",
            headers={"Content-Disposition": "inline; filename=speech.mp3"}
        )
    except Exception as e:
        print(f"[ElevenLabs] TTS error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"TTS error: {str(e)}")

@app.post("/interview/start")
def interview_start(req: StartSessionRequest):
    """Start a new interview session with K2."""
    session_id = str(uuid.uuid4())
    sessions_db[session_id] = []

    # Initial system message with user context
    system_with_context = INTERVIEWER_SYSTEM + f"\n\n[SYSTEM: User's name is {req.name}. Start with a warm open question. Do not reveal you are AI.]"

    prompt = (
        "Return ONLY the next interviewer message in 1-3 warm sentences.\n"
        "Do not include labels, analysis, or extra formatting.\n\n"
        f"User: Hi, I'm {req.name}. Let's begin."
    )

    try:
        opening_text = extract_assistant_reply(call_k2(system_with_context, prompt))
    except Exception as e:
        print(f"[Interview] start fallback due to model error: {e}")
        opening_text = (
            f"Hey {req.name}, great to meet you. "
            "What kind of friendships or connections are you hoping to build right now?"
        )

    if not opening_text:
        raise HTTPException(status_code=500, detail="Model returned an empty opening message")

    sessions_db[session_id].append({"role": "assistant", "content": opening_text})

    return {"session_id": session_id, "message": opening_text}

@app.post("/interview/chat")
def interview_chat(req: ChatRequest):
    """Send a message during the interview with K2."""
    if req.session_id not in sessions_db:
        raise HTTPException(status_code=404, detail="Session not found")

    # Add user message
    sessions_db[req.session_id].append({"role": "user", "content": req.message})

    # Count user turns
    user_turns = sum(1 for msg in sessions_db[req.session_id] if msg["role"] == "user")

    # Prepare system prompt
    system_prompt = INTERVIEWER_SYSTEM
    audio_insights = session_audio_insights.get(req.session_id)
    audio_personality = (audio_insights or {}).get("audio_personality") or {}
    if audio_personality:
        system_prompt += (
            "\n\n[SYSTEM: Adjust your tone to the user's voice profile. "
            f"Use these hints naturally: pace={audio_personality.get('pace')}, "
            f"energy={audio_personality.get('energy')}, "
            f"confidence={audio_personality.get('confidence')}, "
            f"engagement={audio_personality.get('engagement')}.]"
        )
    if user_turns >= 6:
        system_prompt += "\n\n[SYSTEM: You have asked enough questions. Do NOT ask any more questions. Wrap up the conversation warmly in 1-2 sentences without posing any question.]"

    # Build conversation as a single prompt with history
    history_text = "\n".join(
        f"{('User' if m['role'] == 'user' else 'Assistant')}: {m['content']}"
        for m in sessions_db[req.session_id]
    )
    full_prompt = (
        "Conversation so far:\n"
        f"{history_text}\n\n"
        "Return ONLY the next assistant message in 1-3 sentences.\n"
        "No labels, markdown, or analysis."
    )

    try:
        reply = extract_assistant_reply(call_k2(system_prompt, full_prompt))
    except Exception as e:
        print(f"[Interview] chat fallback due to model error: {e}")
        reply = (
            "Thanks for sharing that. I hit a brief hiccup, but I'd still love to keep going. "
            "What is one quality you value most in a close friend?"
        )

    if not reply:
        raise HTTPException(status_code=500, detail="Model returned an empty reply")

    sessions_db[req.session_id].append({"role": "assistant", "content": reply})

    # Detect if done
    assistant_messages = [
        msg["content"] for msg in sessions_db[req.session_id] if msg["role"] == "assistant"
    ]
    repeated_non_question_close = (
        len(assistant_messages) >= 2
        and all("?" not in (msg or "") for msg in assistant_messages[-2:])
    )
    threshold_reached_and_not_question = user_turns >= 6 and "?" not in (reply or "")
    is_done = (
        threshold_reached_and_not_question
        or repeated_non_question_close
        or any(
            phrase in reply.lower()
            for phrase in ["good sense of you", "lovely talking", "enjoyed this", "really lovely"]
        )
    )

    return {
        "message": reply,
        "turn": user_turns,
        "is_complete": is_done
    }

@app.post("/interview/chat-audio")
async def interview_chat_audio(
    session_id: str = Form(...),
    message: str = Form(...),
    audio_file: UploadFile = File(None)
):
    """Send a message during the interview with user audio."""
    import asyncio

    if not GOOGLE_API_KEY:
        raise HTTPException(status_code=400, detail="GOOGLE_API_KEY not set")

    if session_id not in sessions_db:
        raise HTTPException(status_code=404, detail="Session not found")

    # Snapshot previous insights before appending user turn — used for the prompt
    # signal note so we don't have to wait for current-turn audio analysis.
    prev_insights = session_audio_insights.get(session_id)

    sessions_db[session_id].append({"role": "user", "content": message})
    turn_number = sum(1 for m in sessions_db[session_id] if m['role'] == 'user')

    audio_bytes = await audio_file.read() if audio_file is not None else None

    if audio_bytes:
        audio_path = f"audio_samples/{session_id}_{turn_number}.wav"
        open(audio_path, 'wb').write(audio_bytes)

    # Build prompt immediately using previous turn's audio insights (already ready).
    # Current-turn audio analysis runs in parallel with Gemma and is stored for
    # the NEXT turn's signal note — one-turn lag is imperceptible in practice.
    prompt_insights = prev_insights
    prompt = _build_interview_prompt(session_id, prompt_insights)

    async def _run_audio_pipeline():
        """Process current-turn audio; results stored for next turn."""
        if not audio_bytes:
            return None
        try:
            raw_features = await _process_audio_file(audio_bytes)
        except Exception as e:
            print(f"[AUDIO] Pipeline failed, skipping audio insights: {e}")
            return None
        transcript_signals = _extract_transcript_signals(message)
        history = session_audio_history.get(session_id, [])
        calibration = _compute_session_calibration(history, raw_features)
        heuristic = _classify_audio_style_from_features(raw_features, calibration, transcript_signals)
        insights = {
            **raw_features,
            'transcript_signals': transcript_signals,
            'audio_personality': {
                'source': 'heuristic',
                'primary_style': heuristic.get('primary_style', 'balanced'),
                'secondary_style': heuristic.get('brightness', 'balanced'),
                'emotion_state': heuristic.get('emotion_state', 'neutral'),
                'talk_style': heuristic.get('talk_style', 'conversational'),
                'articulation_level': heuristic.get('articulation_level', 'measured'),
                'mbti_like_traits': heuristic.get('mbti_like_traits', []),
                'evaluation_tags': heuristic.get('evaluation_tags', []),
                'trait_descriptors': heuristic.get('trait_descriptors', []),
                'compatibility_insight': heuristic.get('compatibility_note', ''),
                'calibration': calibration,
            },
        }
        session_audio_history.setdefault(session_id, []).append(
            {k: raw_features[k] for k in _CALIBRATION_KEYS if k in raw_features}
        )
        session_audio_insights[session_id] = insights
        # DB write for labeling studio
        filler_rate = transcript_signals.get('filler_rate', 0.0)
        filler_presence = 'high' if filler_rate > 0.10 else ('moderate' if filler_rate > 0.05 else ('low' if filler_rate > 0.01 else 'none'))
        auto_labels = {**insights.get('audio_personality', {}), 'filler_presence': filler_presence}
        conn = _get_db_conn()
        conn.execute(
            "INSERT OR REPLACE INTO audio_labels (session_id, turn, audio_path, features_json, auto_labels_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, turn_number, audio_path, json.dumps(raw_features), json.dumps(auto_labels), int(time.time()))
        )
        conn.commit()
        conn.close()
        # Background: K2 personality + Gemini filler transcription (slow, non-blocking)
        asyncio.create_task(_analyze_personality_background(
            session_id, raw_features, calibration,
            db_turn=turn_number, transcript_signals=transcript_signals,
        ))
        asyncio.create_task(_transcribe_and_update_db(audio_bytes, message, session_id, turn_number))
        return insights

    loop = asyncio.get_event_loop()

    async def _run_gemma():
        model = google.generativeai.GenerativeModel("gemma-4-31b-it")
        return await loop.run_in_executor(None, lambda: model.generate_content(prompt))

    # Run audio processing and Gemma generation in parallel
    audio_result, gemma_response = await asyncio.gather(
        _run_audio_pipeline(),
        _run_gemma(),
    )

    reply = extract_assistant_reply(extract_text_response(gemma_response))
    sessions_db[session_id].append({"role": "assistant", "content": reply})

    audio_insights = audio_result or prev_insights

    user_turns = sum(1 for msg in sessions_db[session_id] if msg["role"] == "user")
    is_done = user_turns >= 14 or any(phrase in reply.lower() for phrase in
             ["good sense of you", "lovely talking", "enjoyed this", "really lovely"])

    return {
        "message": reply,
        "turn": user_turns,
        "is_complete": is_done,
        "audio_insights": audio_insights,
    }

AI_CHAT_SYSTEM = """You are a friendly, thoughtful AI companion on Wavelength — a platform for meaningful connections.
Have warm, genuine conversations. Be curious, empathetic, and engaging.
Keep replies concise (2-4 sentences). Never reveal you are an AI model name."""

ai_chat_sessions_db: dict = {}  # session_id -> message list

@app.post("/ai/chat")
def ai_chat(req: AIChatRequest):
    """Free-form chat with the Wavelength AI."""
    # Create or resume session
    session_id = req.session_id
    if not session_id or session_id not in ai_chat_sessions_db:
        session_id = str(uuid.uuid4())
        ai_chat_sessions_db[session_id] = []

    ai_chat_sessions_db[session_id].append({"role": "user", "content": req.message})

    history_text = "\n".join(
        f"{('User' if m['role'] == 'user' else 'Assistant')}: {m['content']}"
        for m in ai_chat_sessions_db[session_id]
    )
    prompt = (
        f"Conversation so far:\n{history_text}\n\n"
        "Return ONLY the next assistant message in 2-4 sentences. No labels or markdown."
    )

    try:
        reply = extract_assistant_reply(call_k2(AI_CHAT_SYSTEM, prompt))
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"AI unavailable: {e}")

    if not reply:
        raise HTTPException(status_code=500, detail="AI returned an empty reply")

    ai_chat_sessions_db[session_id].append({"role": "assistant", "content": reply})
    return {"session_id": session_id, "message": reply}

AI_CHAT_SYSTEM = """You are a friendly, thoughtful AI companion on Wavelength — a platform for meaningful connections.
Have warm, genuine conversations. Be curious, empathetic, and engaging.
Keep replies concise (2-4 sentences). Never reveal you are an AI model name."""

ai_chat_sessions_db: dict = {}  # session_id -> message list

@app.post("/ai/chat")
def ai_chat(req: AIChatRequest):
    """Free-form chat with the Wavelength AI."""
    # Create or resume session
    session_id = req.session_id
    if not session_id or session_id not in ai_chat_sessions_db:
        session_id = str(uuid.uuid4())
        ai_chat_sessions_db[session_id] = []

    ai_chat_sessions_db[session_id].append({"role": "user", "content": req.message})

    history_text = "\n".join(
        f"{('User' if m['role'] == 'user' else 'Assistant')}: {m['content']}"
        for m in ai_chat_sessions_db[session_id]
    )
    prompt = (
        f"Conversation so far:\n{history_text}\n\n"
        "Return ONLY the next assistant message in 2-4 sentences. No labels or markdown."
    )

    try:
        reply = extract_assistant_reply(call_k2(AI_CHAT_SYSTEM, prompt))
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"AI unavailable: {e}")

    if not reply:
        raise HTTPException(status_code=500, detail="AI returned an empty reply")

    ai_chat_sessions_db[session_id].append({"role": "assistant", "content": reply})
    return {"session_id": session_id, "message": reply}

@app.post("/interview/extract")
def interview_extract(req: InterviewExtractRequest):
    """Extract wavelengthlity from interview transcript."""
    session_id = req.session_id
    user_id = req.user_id

    if user_id not in users_db:
        # Recover gracefully after backend restart by creating a minimal profile.
        recovered_profile = {
            "user_id": user_id,
            "name": (req.name or "User").strip() or "User",
            "age": None,
            "gender": None,
            "photo_url": "https://i.pravatar.cc/300?img=1",
            "wavelengthlity": None,
            "preferred_age_min": None,
            "preferred_age_max": None,
        }
        users_db[user_id] = recovered_profile
        _db_upsert_profile(recovered_profile)

    session_messages = sessions_db.get(session_id) if session_id else None
    if session_messages:
        transcript_messages = session_messages
    elif req.transcript:
        transcript_messages = [
            {"role": t.role, "content": t.content}
            for t in req.transcript
            if (t.role in {"user", "assistant"} and (t.content or "").strip())
        ]
    else:
        raise HTTPException(status_code=404, detail="Session not found")

    if not transcript_messages:
        raise HTTPException(status_code=400, detail="Transcript is empty")

    # Build transcript
    transcript = "\n".join(
        [f"{msg['role'].upper()}: {msg['content']}" for msg in transcript_messages]
    )
    
    # Extract wavelengthlity with K2.
    extract_prompt = f"Here is the interview transcript:\n\n{transcript}\n\nExtract the wavelengthlity profile."
    try:
        wavelengthlity = call_k2_with_fallback(EXTRACTION_SYSTEM, extract_prompt)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Extraction model unavailable: {e}")
    
    # Store in user profile
    users_db[user_id]["wavelengthlity"] = wavelengthlity
    _db_upsert_profile(users_db[user_id])
    
    return {"user_id": user_id, "wavelengthlity": wavelengthlity}

@app.get("/users")
def list_users():
    """List all users."""
    users = []
    for user_id, profile in users_db.items():
        users.append({
            "user_id": user_id,
            "name": profile["name"],
            "age": profile["age"],
            "gender": profile.get("gender"),
            "photo_url": profile["photo_url"],
            "preferred_age_min": profile.get("preferred_age_min"),
            "preferred_age_max": profile.get("preferred_age_max"),
            "has_wavelengthlity": profile["wavelengthlity"] is not None,
            "summary": (profile["wavelengthlity"] or {}).get("summary", "")
        })
    return users

@app.get("/users/{user_id}")
def get_user(user_id: str):
    """Get a user profile by ID."""
    if user_id not in users_db:
        raise HTTPException(status_code=404, detail="User not found")
    return users_db[user_id]


@app.get("/match/potential/{user_id}")
def potential_matches(user_id: str, limit: int = 30):
    """Return ranked potential matches based on profile content similarity."""
    if user_id not in users_db:
        raise HTTPException(status_code=404, detail="User not found")

    source = users_db[user_id]
    if not source.get("wavelengthlity"):
        raise HTTPException(status_code=400, detail="Complete your interview first to get matched")

    ranked = []
    for other_id, other in users_db.items():
        if other_id == user_id:
            continue
        if not other.get("wavelengthlity"):
            continue
        if not _age_within_preference(source, other):
            continue
        if _is_unmatched(user_id, other_id):
            continue

        match = compute_profile_match(source, other)
        ranked.append({
            "user_id": other_id,
            "name": other.get("name"),
            "age": other.get("age"),
            "gender": other.get("gender"),
            "photo_url": other.get("photo_url"),
            "summary": (other.get("wavelengthlity") or {}).get("summary", ""),
            "overall_score": match["overall_score"],
            "dimensions": match["dimensions"],
            "commonalities": match["commonalities"],
            "wavelengthlity": {
                "traits": (other.get("wavelengthlity") or {}).get("traits", {}),
                "values": (other.get("wavelengthlity") or {}).get("values", []),
                "interests": (other.get("wavelengthlity") or {}).get("interests", []),
            },
        })

    ranked.sort(key=lambda m: m["overall_score"], reverse=True)
    limit = max(1, min(limit, 100))
    return {"user_id": user_id, "count": len(ranked), "matches": ranked[:limit]}

@app.post("/match/compatibility")
def match_compatibility(req: CompatibilityRequest):
    """Calculate compatibility between two users using K2."""
    if req.user_id_a not in users_db or req.user_id_b not in users_db:
        raise HTTPException(status_code=404, detail="User not found")
    
    profile_a = users_db[req.user_id_a]
    profile_b = users_db[req.user_id_b]
    
    if not profile_a["wavelengthlity"] or not profile_b["wavelengthlity"]:
        raise HTTPException(status_code=400, detail="One or both users missing wavelengthlity profile")
    
    name_a = profile_a["name"]
    name_b = profile_b["name"]
    
    prompt = f"""Analyze compatibility:

PERSON A — {name_a}:
{json.dumps(profile_a['wavelengthlity'], indent=2)}

PERSON B — {name_b}:
{json.dumps(profile_b['wavelengthlity'], indent=2)}

Reason step by step through their compatibility."""
    
    compatibility = call_k2_with_fallback(COMPATIBILITY_SYSTEM, prompt)
    
    return {
        "user_a": {"id": req.user_id_a, "name": name_a},
        "user_b": {"id": req.user_id_b, "name": name_b},
        "compatibility": compatibility
    }

@app.post("/match/simulate")
def match_simulate(req: SimulationRequest):
    """Simulate a conversation between two users."""
    if req.user_id_a not in users_db or req.user_id_b not in users_db:
        raise HTTPException(status_code=404, detail="User not found")
    
    profile_a = users_db[req.user_id_a]
    profile_b = users_db[req.user_id_b]
    
    if not profile_a["wavelengthlity"] or not profile_b["wavelengthlity"]:
        raise HTTPException(status_code=400, detail="One or both users missing wavelengthlity profile")
    
    name_a = profile_a["name"]
    name_b = profile_b["name"]
    
    # Find a shared interest or energy topic
    energy_a = profile_a["wavelengthlity"].get("energy_topics", [])
    energy_b = profile_b["wavelengthlity"].get("energy_topics", [])
    shared = [e for e in energy_a if e in energy_b]
    topic = shared[0] if shared else (energy_a[0] if energy_a else "travel")
    
    prompt = f"""Simulate a first date conversation between {name_a} and {name_b}.

{name_a}'s wavelengthlity:
{json.dumps(profile_a['wavelengthlity'], indent=2)}

{name_b}'s wavelengthlity:
{json.dumps(profile_b['wavelengthlity'], indent=2)}

Topic to discuss: {topic}

Write 6-8 exchanges showing how they'd actually talk. Show their wavelengthlity through vocabulary, who asks questions, who tells stories."""
    
    simulation = call_k2_with_fallback(SIMULATION_SYSTEM, prompt)
    
    return {"simulation": simulation}

def _dm_key(user_id_a: str, user_id_b: str) -> str:
    """Canonical key for a direct message conversation (order-independent)."""
    return "__".join(sorted([user_id_a, user_id_b]))


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _apply_meetup_feedback_to_profile(req: MeetupFeedbackRequest) -> bool:
    """Adjust user's trait profile based on meetup feedback to affect future matching."""
    source = users_db.get(req.from_user_id)
    target = users_db.get(req.to_user_id)
    if not source or not target:
        return False

    source_w = source.get("wavelengthlity") or {}
    target_w = target.get("wavelengthlity") or {}
    source_traits = source_w.get("traits") or {}
    target_traits = target_w.get("traits") or {}
    if not source_traits or not target_traits:
        return False

    ratings = [
        r for r in [req.chemistry_rating, req.communication_rating, req.safety_rating]
        if isinstance(r, int)
    ]
    avg_rating = (sum(ratings) / len(ratings)) if ratings else 3.0

    positive_signal = req.met and bool(req.would_meet_again) and avg_rating >= 3.5
    negative_signal = req.met and (req.would_meet_again is False or avg_rating <= 2.5)
    if not positive_signal and not negative_signal:
        return False

    if positive_signal:
        step = 0.04 + ((avg_rating - 3.0) / 2.0) * 0.04
    else:
        step = 0.04 + ((3.0 - avg_rating) / 2.0) * 0.04
    step = max(0.02, min(0.10, step))

    updated_traits = dict(source_traits)
    for key in TRAIT_KEYS:
        current = _safe_trait(source_traits, key)
        other = _safe_trait(target_traits, key)
        if positive_signal:
            updated_traits[key] = _clamp01(current + (other - current) * step)
        else:
            # Move slightly away from traits associated with poor outcomes.
            updated_traits[key] = _clamp01(current + (current - other) * step)

    source_w["traits"] = updated_traits
    source["wavelengthlity"] = source_w
    users_db[req.from_user_id] = source
    _db_upsert_profile(source)
    return True


@app.post("/dm/send")
def dm_send(req: DirectMessageRequest):
    """Send a direct message from one user to another."""
    if req.from_user_id not in users_db:
        raise HTTPException(status_code=404, detail="Sender not found")
    if req.to_user_id not in users_db:
        raise HTTPException(status_code=404, detail="Recipient not found")
    if not req.content.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    key = _dm_key(req.from_user_id, req.to_user_id)

    msg = {
        "id": str(uuid.uuid4()),
        "from_user_id": req.from_user_id,
        "to_user_id": req.to_user_id,
        "content": req.content.strip(),
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }

    conn = _get_db_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO direct_messages (id, conversation_key, from_user_id, to_user_id, content, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (msg["id"], key, msg["from_user_id"], msg["to_user_id"], msg["content"], msg["timestamp"]),
    )
    conn.commit()
    conn.close()

    return msg


@app.get("/dm/conversations/{user_id}")
def dm_conversations(user_id: str):
    """Return all conversations for a user — one entry per unique chat partner, with last message."""
    conn = _get_db_conn()
    cur = conn.cursor()

    # Get the most recent message per conversation_key that involves this user
    rows = cur.execute(
        """
        SELECT conversation_key, from_user_id, to_user_id, content, timestamp
        FROM direct_messages
        WHERE from_user_id = ? OR to_user_id = ?
        ORDER BY timestamp ASC
        """,
        (user_id, user_id),
    ).fetchall()
    conn.close()

    # Group by conversation_key, keep last message
    convs: dict = {}
    for row in rows:
        key = row["conversation_key"]
        convs[key] = {
            "conversation_key": key,
            "last_message": {
                "from_user_id": row["from_user_id"],
                "to_user_id": row["to_user_id"],
                "content": row["content"],
                "timestamp": row["timestamp"],
            },
        }

    result = []
    for key, conv in convs.items():
        # Resolve the other user's id from the key (sorted pair joined by __)
        parts = key.split("__")
        other_id = parts[1] if parts[0] == user_id else parts[0]
        # Skip unmatched conversations
        if _is_unmatched(user_id, other_id):
            continue
        other_profile = users_db.get(other_id) or {}
        result.append({
            "other_user_id": other_id,
            "other_user": {
                "user_id": other_id,
                "name": other_profile.get("name", "Unknown"),
                "photo_url": other_profile.get("photo_url", ""),
                "age": other_profile.get("age"),
                "gender": other_profile.get("gender"),
            },
            "last_message": conv["last_message"],
        })

    # Sort by last message timestamp, newest first
    result.sort(key=lambda c: c["last_message"]["timestamp"], reverse=True)
    return {"conversations": result}


@app.get("/dm/{user_id_a}/{user_id_b}")
def dm_get(user_id_a: str, user_id_b: str):
    """Get all direct messages between two users."""
    key = _dm_key(user_id_a, user_id_b)
    conn = _get_db_conn()
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT id, from_user_id, to_user_id, content, timestamp
        FROM direct_messages
        WHERE conversation_key = ?
        ORDER BY timestamp ASC
        """,
        (key,),
    ).fetchall()
    conn.close()

    messages = [
        {
            "id": row["id"],
            "from_user_id": row["from_user_id"],
            "to_user_id": row["to_user_id"],
            "content": row["content"],
            "timestamp": row["timestamp"],
        }
        for row in rows
    ]
    return {"messages": messages}


@app.post("/dm/meetup-feedback")
def dm_meetup_feedback(req: MeetupFeedbackRequest):
    """Store post-meetup feedback and adapt profile for future suggestions."""
    if req.from_user_id not in users_db:
        raise HTTPException(status_code=404, detail="Sender not found")
    if req.to_user_id not in users_db:
        raise HTTPException(status_code=404, detail="Recipient not found")
    if req.from_user_id == req.to_user_id:
        raise HTTPException(status_code=400, detail="Invalid feedback target")

    ratings = [
        ("chemistry_rating", req.chemistry_rating),
        ("communication_rating", req.communication_rating),
        ("safety_rating", req.safety_rating),
    ]
    for field_name, rating in ratings:
        if rating is not None and (rating < 1 or rating > 5):
            raise HTTPException(status_code=400, detail=f"{field_name} must be between 1 and 5")

    if req.met and req.would_meet_again is None:
        raise HTTPException(status_code=400, detail="would_meet_again is required when met=true")

    feedback_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat() + "Z"
    conversation_key = _dm_key(req.from_user_id, req.to_user_id)

    conn = _get_db_conn()
    conn.execute(
        """
        INSERT INTO meetup_feedback (
            id, from_user_id, to_user_id, conversation_key, met,
            chemistry_rating, communication_rating, safety_rating,
            would_meet_again, notes, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            feedback_id,
            req.from_user_id,
            req.to_user_id,
            conversation_key,
            1 if req.met else 0,
            req.chemistry_rating,
            req.communication_rating,
            req.safety_rating,
            None if req.would_meet_again is None else (1 if req.would_meet_again else 0),
            (req.notes or "").strip()[:600],
            now,
        ),
    )
    conn.commit()
    conn.close()

    profile_updated = _apply_meetup_feedback_to_profile(req)

    return {
        "saved": True,
        "feedback_id": feedback_id,
        "profile_updated": profile_updated,
        "message": "Feedback saved. Future suggestions will adapt from this input.",
    }


class UnmatchRequest(BaseModel):
    user_id_a: str
    user_id_b: str


@app.post("/dm/unmatch")
def dm_unmatch(req: UnmatchRequest):
    """Unmatch two users — hides messages and removes from discover on both ends."""
    a, b = req.user_id_a, req.user_id_b
    if a == b:
        raise HTTPException(status_code=400, detail="Cannot unmatch yourself")

    key = frozenset([a, b])
    if key not in unmatches_db:
        unmatches_db.add(key)
        now = datetime.utcnow().isoformat() + "Z"
        conn = _get_db_conn()
        conn.execute(
            "INSERT OR IGNORE INTO unmatches (user_id_a, user_id_b, created_at) VALUES (?, ?, ?)",
            (a, b, now),
        )
        conn.commit()
        conn.close()

    return {"unmatched": True}


@app.post("/seed-demo-users")
def seed_demo_users():
    """Seed 50 diverse demo profiles."""
    removed_before = remove_duplicate_users()

    demo_users = [
        {
            "user_id": str(uuid.uuid4()),
            "name": "Maya",
            "age": 28,
            "gender": "woman",
            "photo_url": "https://randomuser.me/api/portraits/women/44.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.85, "conscientiousness": 0.72, "extraversion": 0.68, "agreeableness": 0.79, "emotional_stability": 0.74, "novelty_seeking": 0.81, "security_need": 0.52},
                "conflict_style": "collaborative", "communication_register": "casual", "reasoning_style": "balanced",
                "values": ["authenticity", "growth", "adventure", "connection"],
                "interests": ["rock climbing", "philosophy", "cooking", "travel"],
                "worldview": "Life is meant to be explored. People are most interesting when they're honest about their flaws.",
                "energy_topics": ["travel stories", "creative projects", "personal growth"],
                "deflection_topics": ["failure", "family conflict"],
                "summary": "A curious soul who climbs mountains and asks deep questions."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Lena",
            "age": 31,
            "gender": "woman",
            "photo_url": "https://randomuser.me/api/portraits/women/68.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.62, "conscientiousness": 0.88, "extraversion": 0.45, "agreeableness": 0.81, "emotional_stability": 0.68, "novelty_seeking": 0.51, "security_need": 0.72},
                "conflict_style": "direct", "communication_register": "formal", "reasoning_style": "analytical",
                "values": ["integrity", "family", "stability", "learning"],
                "interests": ["reading", "chess", "architecture", "classical music"],
                "worldview": "Building something meaningful requires patience, structure, and honest communication.",
                "energy_topics": ["career ambitions", "books", "community"],
                "deflection_topics": ["relationships", "risk-taking"],
                "summary": "A thoughtful architect of her own life, seeking depth over breadth."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Zara",
            "age": 26,
            "gender": "woman",
            "photo_url": "https://randomuser.me/api/portraits/women/17.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.91, "conscientiousness": 0.55, "extraversion": 0.82, "agreeableness": 0.65, "emotional_stability": 0.61, "novelty_seeking": 0.88, "security_need": 0.38},
                "conflict_style": "direct", "communication_register": "mixed", "reasoning_style": "emotional",
                "values": ["freedom", "expression", "justice", "spontaneity"],
                "interests": ["art", "activism", "music", "poetry"],
                "worldview": "The world is broken in interesting ways. We fix it by creating, not by following rules.",
                "energy_topics": ["social change", "creative projects", "late-night conversations"],
                "deflection_topics": ["responsibility", "long-term planning"],
                "summary": "A creative rebel who sees possibility where others see walls."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Alex",
            "age": 29,
            "gender": "man",
            "photo_url": "https://randomuser.me/api/portraits/men/32.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.74, "conscientiousness": 0.81, "extraversion": 0.71, "agreeableness": 0.72, "emotional_stability": 0.79, "novelty_seeking": 0.68, "security_need": 0.58},
                "conflict_style": "collaborative", "communication_register": "casual", "reasoning_style": "balanced",
                "values": ["loyalty", "humor", "excellence", "adventure"],
                "interests": ["hiking", "cooking", "photography", "board games"],
                "worldview": "Good people doing small things well is how the world improves.",
                "energy_topics": ["travel", "food", "outdoor adventures"],
                "deflection_topics": ["ambition", "status"],
                "summary": "A warm pragmatist who believes in doing things right and having fun doing it."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Jordan",
            "age": 32,
            "gender": "non-binary",
            "photo_url": "https://randomuser.me/api/portraits/men/75.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.68, "conscientiousness": 0.76, "extraversion": 0.58, "agreeableness": 0.69, "emotional_stability": 0.81, "novelty_seeking": 0.61, "security_need": 0.65},
                "conflict_style": "avoidant", "communication_register": "formal", "reasoning_style": "analytical",
                "values": ["peace", "wisdom", "sustainability", "community"],
                "interests": ["meditation", "gardening", "science", "environmentalism"],
                "worldview": "We're all part of something larger. Balance and respect for systems is key.",
                "energy_topics": ["nature", "science", "philosophy"],
                "deflection_topics": ["competition", "conflict"],
                "summary": "A systems thinker who finds peace in understanding how things connect."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Sam",
            "age": 27,
            "gender": "man",
            "photo_url": "https://randomuser.me/api/portraits/men/52.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.79, "conscientiousness": 0.68, "extraversion": 0.75, "agreeableness": 0.74, "emotional_stability": 0.72, "novelty_seeking": 0.76, "security_need": 0.48},
                "conflict_style": "collaborative", "communication_register": "casual", "reasoning_style": "balanced",
                "values": ["curiosity", "kindness", "creativity", "independence"],
                "interests": ["video games", "technology", "music production", "travel"],
                "worldview": "The best conversations happen when people are genuinely themselves.",
                "energy_topics": ["new technology", "games", "music"],
                "deflection_topics": ["traditional roles", "criticism"],
                "summary": "A tech-savvy explorer who builds things and connects with people authentically."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Priya",
            "age": 25,
            "gender": "woman",
            "photo_url": "https://randomuser.me/api/portraits/women/26.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.83, "conscientiousness": 0.77, "extraversion": 0.62, "agreeableness": 0.85, "emotional_stability": 0.70, "novelty_seeking": 0.72, "security_need": 0.60},
                "conflict_style": "collaborative", "communication_register": "mixed", "reasoning_style": "balanced",
                "values": ["family", "ambition", "creativity", "empathy"],
                "interests": ["dance", "startups", "food culture", "psychology"],
                "worldview": "You can be driven and warm at the same time. Those aren't opposites.",
                "energy_topics": ["entrepreneurship", "culture", "human behavior"],
                "deflection_topics": ["settling down", "expectations"],
                "summary": "An ambitious empath building her own path without losing her warmth."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Marcus",
            "age": 30,
            "gender": "man",
            "photo_url": "https://randomuser.me/api/portraits/men/11.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.70, "conscientiousness": 0.85, "extraversion": 0.55, "agreeableness": 0.66, "emotional_stability": 0.83, "novelty_seeking": 0.58, "security_need": 0.70},
                "conflict_style": "direct", "communication_register": "formal", "reasoning_style": "analytical",
                "values": ["discipline", "honesty", "growth", "legacy"],
                "interests": ["weightlifting", "investing", "history", "jazz"],
                "worldview": "Consistency over time is how character is built. Everything else is noise.",
                "energy_topics": ["self-improvement", "history", "long-term thinking"],
                "deflection_topics": ["vulnerability", "spontaneity"],
                "summary": "A disciplined builder who plays the long game in everything he does."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Cleo",
            "age": 24,
            "gender": "woman",
            "photo_url": "https://randomuser.me/api/portraits/women/55.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.95, "conscientiousness": 0.48, "extraversion": 0.88, "agreeableness": 0.71, "emotional_stability": 0.57, "novelty_seeking": 0.93, "security_need": 0.32},
                "conflict_style": "direct", "communication_register": "casual", "reasoning_style": "emotional",
                "values": ["fun", "authenticity", "connection", "living fully"],
                "interests": ["festival culture", "comedy", "improv", "spontaneous travel"],
                "worldview": "Life's too short to be serious all the time. Joy is a valid life goal.",
                "energy_topics": ["experiences", "people", "humor"],
                "deflection_topics": ["long-term plans", "structure"],
                "summary": "A free spirit who fills every room with energy and makes strangers feel like friends."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Eli",
            "age": 33,
            "gender": "man",
            "photo_url": "https://randomuser.me/api/portraits/men/64.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.76, "conscientiousness": 0.73, "extraversion": 0.42, "agreeableness": 0.78, "emotional_stability": 0.75, "novelty_seeking": 0.64, "security_need": 0.68},
                "conflict_style": "avoidant", "communication_register": "mixed", "reasoning_style": "balanced",
                "values": ["depth", "quiet", "loyalty", "meaning"],
                "interests": ["film", "writing", "long walks", "cooking for others"],
                "worldview": "Most of life happens in the slow moments people rush past.",
                "energy_topics": ["cinema", "storytelling", "everyday beauty"],
                "deflection_topics": ["career success", "networking"],
                "summary": "A quiet observer who notices the things nobody else does and loves deeply."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Nico",
            "age": 27,
            "gender": "non-binary",
            "photo_url": "https://randomuser.me/api/portraits/men/22.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.88, "conscientiousness": 0.59, "extraversion": 0.72, "agreeableness": 0.80, "emotional_stability": 0.65, "novelty_seeking": 0.85, "security_need": 0.41},
                "conflict_style": "collaborative", "communication_register": "casual", "reasoning_style": "emotional",
                "values": ["queer joy", "community", "art", "fluidity"],
                "interests": ["drag culture", "electronic music", "zine-making", "community organizing"],
                "worldview": "Identity is a creative act. The more people you truly know, the richer your world.",
                "energy_topics": ["queer culture", "music scenes", "creative communities"],
                "deflection_topics": ["traditional structure", "career ladders"],
                "summary": "A radiant community-builder who moves through the world with infectious openness."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Sofia",
            "age": 30,
            "gender": "woman",
            "photo_url": "https://randomuser.me/api/portraits/women/33.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.71, "conscientiousness": 0.82, "extraversion": 0.60, "agreeableness": 0.76, "emotional_stability": 0.78, "novelty_seeking": 0.62, "security_need": 0.66},
                "conflict_style": "direct", "communication_register": "mixed", "reasoning_style": "analytical",
                "values": ["financial independence", "travel", "health", "clarity"],
                "interests": ["yoga", "personal finance", "road trips", "podcasts"],
                "worldview": "You earn your freedom by being intentional with your time and money.",
                "energy_topics": ["travel hacking", "wellness routines", "self-sufficiency"],
                "deflection_topics": ["dependence", "vagueness"],
                "summary": "A grounded optimist who plans meticulously so she can be spontaneous with confidence."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Darius",
            "age": 34,
            "gender": "man",
            "photo_url": "https://randomuser.me/api/portraits/men/43.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.65, "conscientiousness": 0.90, "extraversion": 0.50, "agreeableness": 0.63, "emotional_stability": 0.85, "novelty_seeking": 0.52, "security_need": 0.75},
                "conflict_style": "direct", "communication_register": "formal", "reasoning_style": "analytical",
                "values": ["excellence", "loyalty", "mentorship", "legacy"],
                "interests": ["basketball analytics", "chess", "stoic philosophy", "cooking"],
                "worldview": "Mastery is a lifetime project. The goal is to be excellent at the things that matter.",
                "energy_topics": ["strategy", "mentorship", "peak performance"],
                "deflection_topics": ["shortcuts", "small talk"],
                "summary": "A quietly intense achiever who respects depth and dismisses noise."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Aisha",
            "age": 25,
            "gender": "woman",
            "photo_url": "https://randomuser.me/api/portraits/women/12.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.90, "conscientiousness": 0.70, "extraversion": 0.78, "agreeableness": 0.84, "emotional_stability": 0.67, "novelty_seeking": 0.87, "security_need": 0.44},
                "conflict_style": "collaborative", "communication_register": "casual", "reasoning_style": "emotional",
                "values": ["storytelling", "diaspora culture", "friendship", "creativity"],
                "interests": ["afrobeats", "film production", "fashion", "travel to Africa"],
                "worldview": "Our stories are our power. I want to document the ones that get overlooked.",
                "energy_topics": ["African cinema", "fashion as identity", "cultural preservation"],
                "deflection_topics": ["assimilation", "settling"],
                "summary": "A vivid storyteller fueled by cultural pride and an eye for beauty."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Tom",
            "age": 29,
            "gender": "man",
            "photo_url": "https://randomuser.me/api/portraits/men/15.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.60, "conscientiousness": 0.78, "extraversion": 0.83, "agreeableness": 0.73, "emotional_stability": 0.76, "novelty_seeking": 0.66, "security_need": 0.57},
                "conflict_style": "collaborative", "communication_register": "casual", "reasoning_style": "balanced",
                "values": ["fun", "friendship", "loyalty", "sports"],
                "interests": ["fantasy football", "craft beer", "stand-up comedy", "barbecue"],
                "worldview": "Life is better when you're surrounded by people who make you laugh.",
                "energy_topics": ["sports", "weekend adventures", "group dynamics"],
                "deflection_topics": ["deep introspection", "vulnerability"],
                "summary": "A reliably good time who shows love through showing up and cracking jokes."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Ingrid",
            "age": 31,
            "gender": "woman",
            "photo_url": "https://randomuser.me/api/portraits/women/48.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.78, "conscientiousness": 0.84, "extraversion": 0.42, "agreeableness": 0.77, "emotional_stability": 0.80, "novelty_seeking": 0.60, "security_need": 0.70},
                "conflict_style": "avoidant", "communication_register": "formal", "reasoning_style": "analytical",
                "values": ["precision", "nature", "slow living", "craft"],
                "interests": ["ceramics", "Scandinavian design", "hiking", "fermentation"],
                "worldview": "Quality over quantity in everything: objects, relationships, experiences.",
                "energy_topics": ["craft and making", "design philosophy", "nature"],
                "deflection_topics": ["hustle culture", "social media"],
                "summary": "A careful craftsperson who builds her life with the same intentionality as her pottery."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Rafael",
            "age": 26,
            "gender": "man",
            "photo_url": "https://randomuser.me/api/portraits/men/36.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.86, "conscientiousness": 0.58, "extraversion": 0.90, "agreeableness": 0.70, "emotional_stability": 0.60, "novelty_seeking": 0.91, "security_need": 0.35},
                "conflict_style": "direct", "communication_register": "casual", "reasoning_style": "emotional",
                "values": ["passion", "soccer", "family", "spontaneity"],
                "interests": ["soccer", "salsa dancing", "street food", "travel"],
                "worldview": "Emotion is not weakness — it's how you know you're alive.",
                "energy_topics": ["soccer tactics", "Latin culture", "live music"],
                "deflection_topics": ["emotional distance", "rigid plans"],
                "summary": "A fiery, warm-hearted connector who lives fully and loves loudly."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Hannah",
            "age": 33,
            "gender": "woman",
            "photo_url": "https://randomuser.me/api/portraits/women/62.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.74, "conscientiousness": 0.80, "extraversion": 0.55, "agreeableness": 0.82, "emotional_stability": 0.73, "novelty_seeking": 0.63, "security_need": 0.67},
                "conflict_style": "collaborative", "communication_register": "mixed", "reasoning_style": "balanced",
                "values": ["home", "community", "honesty", "growth"],
                "interests": ["gardening", "book clubs", "baking", "volunteering"],
                "worldview": "A life well-lived is woven from small kindnesses and consistent care.",
                "energy_topics": ["community building", "food", "personal stories"],
                "deflection_topics": ["ambition for its own sake", "drama"],
                "summary": "A warm community anchor who finds profound meaning in everyday acts of care."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Kwame",
            "age": 28,
            "gender": "man",
            "photo_url": "https://randomuser.me/api/portraits/men/28.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.82, "conscientiousness": 0.74, "extraversion": 0.65, "agreeableness": 0.72, "emotional_stability": 0.77, "novelty_seeking": 0.79, "security_need": 0.50},
                "conflict_style": "direct", "communication_register": "mixed", "reasoning_style": "balanced",
                "values": ["social justice", "education", "creativity", "community"],
                "interests": ["hip-hop history", "social entrepreneurship", "basketball", "poetry"],
                "worldview": "Culture is infrastructure. You can't separate who we are from the art we make.",
                "energy_topics": ["music history", "systemic change", "black creativity"],
                "deflection_topics": ["apathy", "performative activism"],
                "summary": "A culturally rooted thinker who wants to build things that last beyond him."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Mei",
            "age": 27,
            "gender": "woman",
            "photo_url": "https://randomuser.me/api/portraits/women/39.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.80, "conscientiousness": 0.86, "extraversion": 0.48, "agreeableness": 0.79, "emotional_stability": 0.72, "novelty_seeking": 0.67, "security_need": 0.63},
                "conflict_style": "avoidant", "communication_register": "formal", "reasoning_style": "analytical",
                "values": ["family", "diligence", "beauty", "self-improvement"],
                "interests": ["calligraphy", "tea ceremony", "running", "literature"],
                "worldview": "Discipline practiced with love becomes a form of artistry.",
                "energy_topics": ["Japanese aesthetics", "running", "craft"],
                "deflection_topics": ["conflict", "vulnerability"],
                "summary": "A disciplined aesthete who finds harmony between rigor and beauty."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Jake",
            "age": 24,
            "gender": "man",
            "photo_url": "https://randomuser.me/api/portraits/men/5.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.69, "conscientiousness": 0.55, "extraversion": 0.80, "agreeableness": 0.68, "emotional_stability": 0.63, "novelty_seeking": 0.82, "security_need": 0.38},
                "conflict_style": "avoidant", "communication_register": "casual", "reasoning_style": "emotional",
                "values": ["freedom", "adventure", "good vibes", "loyalty to friends"],
                "interests": ["surfing", "van life", "music festivals", "photography"],
                "worldview": "The best plan is no plan. Wander until something calls you.",
                "energy_topics": ["outdoor adventure", "music", "travel"],
                "deflection_topics": ["commitment", "routine"],
                "summary": "A sun-chasing free spirit who documents his adventures and lives without a fixed plan."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Valentina",
            "age": 32,
            "gender": "woman",
            "photo_url": "https://randomuser.me/api/portraits/women/21.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.76, "conscientiousness": 0.88, "extraversion": 0.67, "agreeableness": 0.75, "emotional_stability": 0.82, "novelty_seeking": 0.60, "security_need": 0.69},
                "conflict_style": "direct", "communication_register": "formal", "reasoning_style": "analytical",
                "values": ["ambition", "elegance", "family", "excellence"],
                "interests": ["architecture", "wine", "classical ballet", "international travel"],
                "worldview": "Everything worth having takes time, effort, and a certain kind of grace.",
                "energy_topics": ["design", "culture", "career", "travel"],
                "deflection_topics": ["mediocrity", "chaos"],
                "summary": "An elegant achiever who builds a beautiful life with deliberate care."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Owen",
            "age": 35,
            "gender": "man",
            "photo_url": "https://randomuser.me/api/portraits/men/60.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.72, "conscientiousness": 0.76, "extraversion": 0.52, "agreeableness": 0.80, "emotional_stability": 0.84, "novelty_seeking": 0.57, "security_need": 0.72},
                "conflict_style": "collaborative", "communication_register": "mixed", "reasoning_style": "balanced",
                "values": ["fatherhood", "patience", "growth", "humor"],
                "interests": ["woodworking", "raising kids", "podcasts", "long-distance cycling"],
                "worldview": "Slow and steady is underrated. Most good things happen over years, not weeks.",
                "energy_topics": ["parenthood", "craft", "personal development"],
                "deflection_topics": ["urgency", "social drama"],
                "summary": "A steady, patient builder of both furniture and long-lasting relationships."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Nadia",
            "age": 29,
            "gender": "woman",
            "photo_url": "https://randomuser.me/api/portraits/women/9.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.93, "conscientiousness": 0.62, "extraversion": 0.74, "agreeableness": 0.68, "emotional_stability": 0.58, "novelty_seeking": 0.90, "security_need": 0.36},
                "conflict_style": "direct", "communication_register": "casual", "reasoning_style": "emotional",
                "values": ["liberation", "sensory experience", "art", "authenticity"],
                "interests": ["contemporary dance", "psychedelic research", "fashion", "underground art"],
                "worldview": "The body knows things the mind hasn't caught up to yet.",
                "energy_topics": ["consciousness", "movement", "avant-garde culture"],
                "deflection_topics": ["convention", "overthinking"],
                "summary": "An embodied adventurer navigating life through sensation, instinct, and radical honesty."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Ben",
            "age": 31,
            "gender": "man",
            "photo_url": "https://randomuser.me/api/portraits/men/47.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.77, "conscientiousness": 0.72, "extraversion": 0.61, "agreeableness": 0.83, "emotional_stability": 0.74, "novelty_seeking": 0.70, "security_need": 0.59},
                "conflict_style": "collaborative", "communication_register": "casual", "reasoning_style": "balanced",
                "values": ["science", "wonder", "kindness", "humor"],
                "interests": ["astronomy", "sci-fi novels", "improv comedy", "rock climbing"],
                "wordview": "The universe is absurdly large and that's somehow comforting.",
                "energy_topics": ["space", "speculative fiction", "improv"],
                "deflection_topics": ["cynicism", "office politics"],
                "summary": "A gentle nerd who finds awe in the cosmos and connection in laughter."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Leila",
            "age": 26,
            "gender": "woman",
            "photo_url": "https://randomuser.me/api/portraits/women/14.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.84, "conscientiousness": 0.75, "extraversion": 0.56, "agreeableness": 0.80, "emotional_stability": 0.69, "novelty_seeking": 0.77, "security_need": 0.55},
                "conflict_style": "collaborative", "communication_register": "mixed", "reasoning_style": "balanced",
                "values": ["poetry", "spirituality", "cultural roots", "connection"],
                "interests": ["Persian poetry", "calligraphy", "meditation", "cooking"],
                "worldview": "Beauty and sadness are two sides of the same door.",
                "energy_topics": ["poetry", "Iranian culture", "spiritual practice"],
                "deflection_topics": ["superficiality", "fast pace"],
                "summary": "A contemplative soul steeped in poetry who moves through the world with quiet depth."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Chris",
            "age": 30,
            "gender": "man",
            "photo_url": "https://randomuser.me/api/portraits/men/19.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.73, "conscientiousness": 0.79, "extraversion": 0.77, "agreeableness": 0.71, "emotional_stability": 0.80, "novelty_seeking": 0.65, "security_need": 0.60},
                "conflict_style": "direct", "communication_register": "casual", "reasoning_style": "balanced",
                "values": ["entrepreneurship", "hustle", "loyalty", "impact"],
                "interests": ["startups", "networking", "CrossFit", "travel hacking"],
                "worldview": "Build something real, surround yourself with people who push you.",
                "energy_topics": ["startups", "fitness", "ambition"],
                "deflection_topics": ["complacency", "small thinking"],
                "summary": "A high-energy builder who's always in motion and brings people along with him."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Yuki",
            "age": 24,
            "gender": "woman",
            "photo_url": "https://randomuser.me/api/portraits/women/42.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.88, "conscientiousness": 0.64, "extraversion": 0.53, "agreeableness": 0.82, "emotional_stability": 0.66, "novelty_seeking": 0.83, "security_need": 0.48},
                "conflict_style": "avoidant", "communication_register": "casual", "reasoning_style": "emotional",
                "values": ["imagination", "gentleness", "anime", "friendship"],
                "interests": ["manga", "game design", "nature walks", "journaling"],
                "worldview": "Reality is just one layer. Stories let us live in all the others.",
                "energy_topics": ["storytelling", "anime worlds", "creativity"],
                "deflection_topics": ["confrontation", "social pressure"],
                "summary": "A dreamy storyteller who lives between worlds and finds magic in quiet things."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Andre",
            "age": 36,
            "gender": "man",
            "photo_url": "https://randomuser.me/api/portraits/men/81.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.68, "conscientiousness": 0.88, "extraversion": 0.44, "agreeableness": 0.70, "emotional_stability": 0.86, "novelty_seeking": 0.50, "security_need": 0.78},
                "conflict_style": "direct", "communication_register": "formal", "reasoning_style": "analytical",
                "values": ["discipline", "faith", "family", "financial literacy"],
                "interests": ["real estate investing", "bible study", "golf", "mentoring youth"],
                "worldview": "Your legacy is the sum of your habits over decades.",
                "energy_topics": ["wealth building", "mentorship", "faith"],
                "deflection_topics": ["shortcuts", "short-term thinking"],
                "summary": "A faith-driven wealth builder mentoring the next generation while building his own legacy."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Carmen",
            "age": 27,
            "gender": "woman",
            "photo_url": "https://randomuser.me/api/portraits/women/57.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.86, "conscientiousness": 0.67, "extraversion": 0.85, "agreeableness": 0.74, "emotional_stability": 0.62, "novelty_seeking": 0.88, "security_need": 0.40},
                "conflict_style": "direct", "communication_register": "casual", "reasoning_style": "emotional",
                "values": ["passion", "culture", "music", "experience"],
                "interests": ["flamenco", "travel", "food", "social media"],
                "worldview": "Passion is the only compass worth following.",
                "energy_topics": ["music", "cultural experiences", "romance"],
                "deflection_topics": ["boredom", "routine"],
                "summary": "An intense, expressive firecracker who chases experiences and radiates passionate energy."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Felix",
            "age": 29,
            "gender": "man",
            "photo_url": "https://randomuser.me/api/portraits/men/55.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.90, "conscientiousness": 0.65, "extraversion": 0.58, "agreeableness": 0.76, "emotional_stability": 0.70, "novelty_seeking": 0.87, "security_need": 0.42},
                "conflict_style": "collaborative", "communication_register": "mixed", "reasoning_style": "balanced",
                "values": ["philosophy", "music", "ethics", "intellectual honesty"],
                "interests": ["jazz piano", "moral philosophy", "film criticism", "coffee"],
                "worldview": "Certainty is overrated. The best conversations end with more questions.",
                "energy_topics": ["ethics", "film", "jazz", "ideas"],
                "deflection_topics": ["small talk", "certainty"],
                "summary": "A jazz-playing philosopher who lives in the questions and finds beauty in ambiguity."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Tanya",
            "age": 33,
            "gender": "woman",
            "photo_url": "https://randomuser.me/api/portraits/women/71.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.70, "conscientiousness": 0.84, "extraversion": 0.63, "agreeableness": 0.77, "emotional_stability": 0.80, "novelty_seeking": 0.59, "security_need": 0.71},
                "conflict_style": "direct", "communication_register": "mixed", "reasoning_style": "balanced",
                "values": ["health", "motherhood", "self-mastery", "community"],
                "interests": ["marathon running", "nutrition", "parenting", "mentoring women"],
                "worldview": "Your body is your foundation. Take care of it and everything else gets clearer.",
                "energy_topics": ["fitness", "parenting", "women's empowerment"],
                "deflection_topics": ["excuses", "passivity"],
                "summary": "A fierce and focused athlete-mom who mentors women to own their strength."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Soren",
            "age": 26,
            "gender": "non-binary",
            "photo_url": "https://randomuser.me/api/portraits/men/37.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.94, "conscientiousness": 0.56, "extraversion": 0.60, "agreeableness": 0.78, "emotional_stability": 0.61, "novelty_seeking": 0.92, "security_need": 0.35},
                "conflict_style": "direct", "communication_register": "casual", "reasoning_style": "emotional",
                "values": ["queerness", "climate justice", "art", "radical care"],
                "interests": ["climate activism", "experimental film", "queer theory", "urban farming"],
                "worldview": "The personal is political and the political needs to be beautiful.",
                "energy_topics": ["climate", "queer futures", "experimental art"],
                "deflection_topics": ["hierarchy", "traditional timelines"],
                "summary": "A climate-activist filmmaker who insists the revolution needs to be aesthetically stunning."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Grace",
            "age": 25,
            "gender": "woman",
            "photo_url": "https://randomuser.me/api/portraits/women/29.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.78, "conscientiousness": 0.82, "extraversion": 0.65, "agreeableness": 0.85, "emotional_stability": 0.74, "novelty_seeking": 0.68, "security_need": 0.62},
                "conflict_style": "collaborative", "communication_register": "mixed", "reasoning_style": "balanced",
                "values": ["kindness", "education", "faith", "service"],
                "interests": ["teaching", "gospel music", "community service", "journaling"],
                "worldview": "You can't pour from an empty cup, but you were made to pour.",
                "energy_topics": ["education", "faith", "community"],
                "deflection_topics": ["cynicism", "self-centeredness"],
                "summary": "A devoted teacher who pours herself into her students and finds her strength in service."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Tariq",
            "age": 30,
            "gender": "man",
            "photo_url": "https://randomuser.me/api/portraits/men/69.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.75, "conscientiousness": 0.79, "extraversion": 0.70, "agreeableness": 0.73, "emotional_stability": 0.78, "novelty_seeking": 0.72, "security_need": 0.55},
                "conflict_style": "collaborative", "communication_register": "casual", "reasoning_style": "balanced",
                "values": ["excellence", "culture", "humor", "integrity"],
                "interests": ["stand-up comedy", "basketball", "investing", "food"],
                "worldview": "You can be serious about your goals and still laugh at everything.",
                "energy_topics": ["comedy", "sports", "culture", "money"],
                "deflection_topics": ["toxic positivity", "inauthenticity"],
                "summary": "A sharp, funny man who's just as likely to make you think as to make you laugh."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Hana",
            "age": 28,
            "gender": "woman",
            "photo_url": "https://randomuser.me/api/portraits/women/35.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.83, "conscientiousness": 0.77, "extraversion": 0.48, "agreeableness": 0.82, "emotional_stability": 0.71, "novelty_seeking": 0.75, "security_need": 0.58},
                "conflict_style": "avoidant", "communication_register": "mixed", "reasoning_style": "emotional",
                "values": ["empathy", "healing", "nature", "slow living"],
                "interests": ["therapy", "hiking", "herbal medicine", "memoir writing"],
                "worldview": "Healing isn't linear but it's always possible.",
                "energy_topics": ["mental health", "nature therapy", "personal essays"],
                "deflection_topics": ["urgency", "ego"],
                "summary": "A gentle healer who tends to others' wounds with the same care she tends her garden."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Viktor",
            "age": 34,
            "gender": "man",
            "photo_url": "https://randomuser.me/api/portraits/men/91.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.66, "conscientiousness": 0.91, "extraversion": 0.40, "agreeableness": 0.65, "emotional_stability": 0.88, "novelty_seeking": 0.48, "security_need": 0.80},
                "conflict_style": "direct", "communication_register": "formal", "reasoning_style": "analytical",
                "values": ["precision", "loyalty", "structure", "craftsmanship"],
                "interests": ["mechanical engineering", "chess", "watchmaking", "classical music"],
                "worldview": "Most problems are solved by thinking more carefully and acting less impulsively.",
                "energy_topics": ["engineering", "precision crafts", "strategy"],
                "deflection_topics": ["emotion-driven decisions", "chaos"],
                "summary": "A methodical engineer who applies the same precision to life as to his intricate machines."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Rosa",
            "age": 27,
            "gender": "woman",
            "photo_url": "https://randomuser.me/api/portraits/women/51.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.87, "conscientiousness": 0.71, "extraversion": 0.79, "agreeableness": 0.80, "emotional_stability": 0.67, "novelty_seeking": 0.84, "security_need": 0.43},
                "conflict_style": "direct", "communication_register": "casual", "reasoning_style": "emotional",
                "values": ["joy", "culture", "community", "color"],
                "interests": ["mural art", "Latin dance", "organizing block parties", "photography"],
                "worldview": "Public space belongs to everyone. Let's make it beautiful.",
                "energy_topics": ["public art", "neighborhood culture", "celebration"],
                "deflection_topics": ["isolation", "pessimism"],
                "summary": "A color-obsessed muralist who believes art is how a neighborhood talks to itself."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Daniel",
            "age": 23,
            "gender": "man",
            "photo_url": "https://randomuser.me/api/portraits/men/8.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.81, "conscientiousness": 0.62, "extraversion": 0.72, "agreeableness": 0.75, "emotional_stability": 0.64, "novelty_seeking": 0.80, "security_need": 0.44},
                "conflict_style": "collaborative", "communication_register": "casual", "reasoning_style": "balanced",
                "values": ["creativity", "friendship", "ambition", "music"],
                "interests": ["music production", "sneakers", "college football", "entrepreneurship"],
                "worldview": "We're all just figuring it out. Might as well have fun doing it.",
                "energy_topics": ["music", "fashion", "ambition", "college life"],
                "deflection_topics": ["settling", "overthinking"],
                "summary": "A young creative with big dreams, genuine energy, and an eye for what's next."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Simone",
            "age": 36,
            "gender": "woman",
            "photo_url": "https://randomuser.me/api/portraits/women/64.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.73, "conscientiousness": 0.85, "extraversion": 0.58, "agreeableness": 0.77, "emotional_stability": 0.82, "novelty_seeking": 0.60, "security_need": 0.70},
                "conflict_style": "direct", "communication_register": "formal", "reasoning_style": "analytical",
                "values": ["strategy", "family", "financial freedom", "mentorship"],
                "interests": ["corporate law", "travel", "yoga", "mentoring young women"],
                "worldview": "Earn the life you want. Then use it to open doors for others.",
                "energy_topics": ["career strategy", "mentorship", "financial independence"],
                "deflection_topics": ["drama", "victimhood"],
                "summary": "A commanding attorney and mentor who built her table from scratch and keeps pulling up chairs."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Liam",
            "age": 25,
            "gender": "man",
            "photo_url": "https://randomuser.me/api/portraits/men/25.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.75, "conscientiousness": 0.68, "extraversion": 0.74, "agreeableness": 0.70, "emotional_stability": 0.69, "novelty_seeking": 0.78, "security_need": 0.48},
                "conflict_style": "avoidant", "communication_register": "casual", "reasoning_style": "balanced",
                "values": ["fun", "exploration", "honesty", "good food"],
                "interests": ["travel", "cooking", "video essays", "soccer"],
                "worldview": "You don't have to have it figured out to start living well.",
                "energy_topics": ["travel", "food culture", "internet culture"],
                "deflection_topics": ["pressure", "comparison"],
                "summary": "A curious twenty-something who cooks to connect and travels to learn who he is."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Amara",
            "age": 29,
            "gender": "woman",
            "photo_url": "https://randomuser.me/api/portraits/women/7.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.89, "conscientiousness": 0.73, "extraversion": 0.66, "agreeableness": 0.81, "emotional_stability": 0.70, "novelty_seeking": 0.85, "security_need": 0.46},
                "conflict_style": "collaborative", "communication_register": "casual", "reasoning_style": "emotional",
                "values": ["healing", "sisterhood", "spirituality", "travel"],
                "interests": ["sound healing", "Afrofuturism", "natural hair culture", "travel"],
                "worldview": "Healing ourselves is how we heal our communities.",
                "energy_topics": ["spirituality", "culture", "healing", "Afrofuturism"],
                "deflection_topics": ["toxic environments", "inauthenticity"],
                "summary": "A spiritually grounded healer who weaves together culture, wellness, and collective liberation."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Patrick",
            "age": 32,
            "gender": "man",
            "photo_url": "https://randomuser.me/api/portraits/men/41.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.67, "conscientiousness": 0.80, "extraversion": 0.73, "agreeableness": 0.72, "emotional_stability": 0.81, "novelty_seeking": 0.61, "security_need": 0.63},
                "conflict_style": "collaborative", "communication_register": "casual", "reasoning_style": "balanced",
                "values": ["family", "humor", "hard work", "community"],
                "interests": ["rugby", "BBQ", "pub quizzes", "DIY home projects"],
                "worldview": "Life is simple if you don't overcomplicate it: work hard, laugh often, look after people.",
                "energy_topics": ["sports", "food", "family", "community"],
                "deflection_topics": ["abstraction", "overthinking"],
                "summary": "A salt-of-the-earth man who fixes things with his hands and holds his community together."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Elena",
            "age": 26,
            "gender": "woman",
            "photo_url": "https://randomuser.me/api/portraits/women/18.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.82, "conscientiousness": 0.76, "extraversion": 0.55, "agreeableness": 0.79, "emotional_stability": 0.68, "novelty_seeking": 0.80, "security_need": 0.52},
                "conflict_style": "collaborative", "communication_register": "mixed", "reasoning_style": "balanced",
                "values": ["literature", "coffee culture", "feminism", "travel"],
                "interests": ["writing", "foreign films", "independent bookstores", "cycling"],
                "worldview": "A good sentence can change the shape of your thinking.",
                "energy_topics": ["books", "writing craft", "culture criticism"],
                "deflection_topics": ["vapidity", "spectacle"],
                "summary": "A careful reader and sharp writer who finds the world endlessly worth paying attention to."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Devin",
            "age": 28,
            "gender": "man",
            "photo_url": "https://randomuser.me/api/portraits/men/33.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.78, "conscientiousness": 0.75, "extraversion": 0.68, "agreeableness": 0.71, "emotional_stability": 0.76, "novelty_seeking": 0.73, "security_need": 0.54},
                "conflict_style": "collaborative", "communication_register": "casual", "reasoning_style": "balanced",
                "values": ["innovation", "community", "music", "honesty"],
                "interests": ["tech entrepreneurship", "gospel music", "urban community", "basketball"],
                "worldview": "Technology should serve people, not the other way around.",
                "energy_topics": ["civic tech", "culture", "sports", "entrepreneurship"],
                "deflection_topics": ["exploitative systems", "performative charity"],
                "summary": "A community-minded technologist building tools for people who usually get left behind."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Isabelle",
            "age": 31,
            "gender": "woman",
            "photo_url": "https://randomuser.me/api/portraits/women/46.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.81, "conscientiousness": 0.79, "extraversion": 0.52, "agreeableness": 0.83, "emotional_stability": 0.74, "novelty_seeking": 0.72, "security_need": 0.60},
                "conflict_style": "collaborative", "communication_register": "mixed", "reasoning_style": "emotional",
                "values": ["beauty", "intimacy", "art", "depth"],
                "interests": ["portrait photography", "wine", "poetry slams", "interior design"],
                "worldview": "Beauty is everywhere but most people are too distracted to notice.",
                "energy_topics": ["photography", "art", "intimate conversation"],
                "deflection_topics": ["shallowness", "noise"],
                "summary": "A portrait photographer who sees the soul behind the face and hosts dinners worth remembering."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Zoe",
            "age": 26,
            "gender": "woman",
            "photo_url": "https://randomuser.me/api/portraits/women/3.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.85, "conscientiousness": 0.69, "extraversion": 0.76, "agreeableness": 0.78, "emotional_stability": 0.65, "novelty_seeking": 0.82, "security_need": 0.43},
                "conflict_style": "direct", "communication_register": "casual", "reasoning_style": "emotional",
                "values": ["environmental justice", "veganism", "community", "music"],
                "interests": ["climate podcasts", "diy music", "urban farming", "cycling"],
                "worldview": "Every choice is political. Might as well make the ones that align with your values.",
                "energy_topics": ["climate action", "ethical living", "indie music"],
                "deflection_topics": ["corporate greenwashing", "apathy"],
                "summary": "A principled activist who lives her values loudly and finds joy in collective action."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Miles",
            "age": 31,
            "gender": "man",
            "photo_url": "https://randomuser.me/api/portraits/men/77.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.80, "conscientiousness": 0.74, "extraversion": 0.63, "agreeableness": 0.74, "emotional_stability": 0.79, "novelty_seeking": 0.76, "security_need": 0.53},
                "conflict_style": "collaborative", "communication_register": "casual", "reasoning_style": "balanced",
                "values": ["creativity", "fatherhood", "music", "legacy"],
                "interests": ["jazz trumpet", "producing music", "fatherhood", "documentary films"],
                "worldview": "Art is how you leave something behind that matters.",
                "energy_topics": ["music", "fatherhood", "storytelling"],
                "deflection_topics": ["materialism", "hustle for its own sake"],
                "summary": "A jazz musician and devoted dad who measures success by what he creates and who he raises."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Nour",
            "age": 28,
            "gender": "woman",
            "photo_url": "https://randomuser.me/api/portraits/women/23.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.87, "conscientiousness": 0.78, "extraversion": 0.57, "agreeableness": 0.83, "emotional_stability": 0.71, "novelty_seeking": 0.79, "security_need": 0.54},
                "conflict_style": "collaborative", "communication_register": "mixed", "reasoning_style": "balanced",
                "values": ["identity", "feminism", "storytelling", "healing"],
                "interests": ["Arabic literature", "documentary filmmaking", "cooking", "meditation"],
                "worldview": "Telling your own story before someone else does is an act of survival.",
                "energy_topics": ["Arab identity", "feminism", "documentary film", "food as memory"],
                "deflection_topics": ["stereotypes", "silencing"],
                "summary": "A documentary filmmaker reclaiming her own narrative one story at a time."
            }
        },
        {
            "user_id": str(uuid.uuid4()),
            "name": "Gabriel",
            "age": 30,
            "gender": "man",
            "photo_url": "https://randomuser.me/api/portraits/men/88.jpg",
            "wavelengthlity": {
                "traits": {"openness": 0.84, "conscientiousness": 0.70, "extraversion": 0.79, "agreeableness": 0.76, "emotional_stability": 0.73, "novelty_seeking": 0.81, "security_need": 0.46},
                "conflict_style": "collaborative", "communication_register": "casual", "reasoning_style": "balanced",
                "values": ["adventure", "connection", "optimism", "growth"],
                "interests": ["mountaineering", "languages", "street photography", "cooking local food"],
                "worldview": "The world is incomprehensibly generous if you're willing to show up for it.",
                "energy_topics": ["adventure travel", "languages", "photography", "human connection"],
                "deflection_topics": ["cynicism", "staying put"],
                "summary": "An adventure-hungry polyglot who collects stories from every corner of the world."
            }
        }
    ]

    existing_ids_by_name = {
        (profile.get("name") or "").strip().lower(): existing_id
        for existing_id, profile in users_db.items()
        if profile.get("name")
    }

    for user in demo_users:
        normalized_name = (user.get("name") or "").strip().lower()
        if normalized_name in existing_ids_by_name:
            user["user_id"] = existing_ids_by_name[normalized_name]
        users_db[user["user_id"]] = user
        _db_upsert_profile(user)
        existing_ids_by_name[normalized_name] = user["user_id"]

    removed_after = remove_duplicate_users()
    if removed_before > 0 or removed_after > 0:
        _sync_profiles_to_db()

    return {
        "seeded": len(demo_users),
        "deduped": removed_before + removed_after,
        "users": demo_users,
    }


@app.post("/seed-test-user")
def seed_test_user():
    """Create a reusable preset user with wavelengthlity for fast testing."""
    test_user = {
        "user_id": "test-user-001",
        "name": "Test User",
        "age": 27,
        "gender": "non-binary",
        "photo_url": "https://randomuser.me/api/portraits/lego/1.jpg",
        "preferred_age_min": 24,
        "preferred_age_max": 32,
        "wavelengthlity": {
            "traits": {
                "openness": 0.82,
                "conscientiousness": 0.69,
                "extraversion": 0.64,
                "agreeableness": 0.78,
                "emotional_stability": 0.71,
                "novelty_seeking": 0.76,
                "security_need": 0.49,
            },
            "conflict_style": "collaborative",
            "communication_register": "mixed",
            "reasoning_style": "balanced",
            "values": ["friendship", "growth", "authenticity", "curiosity"],
            "interests": ["hiking", "music", "coffee chats", "podcasts"],
            "worldview": "Connection grows from shared curiosity and consistent kindness.",
            "energy_topics": ["new experiences", "creative work", "human behavior"],
            "deflection_topics": ["status games", "superficial networking"],
            "summary": "A curious, grounded person who values deep friendship and honest conversation.",
        },
    }

    users_db[test_user["user_id"]] = test_user
    _db_upsert_profile(test_user)
    return {"created": True, "user": test_user}


@app.get("/audio/samples")
def get_audio_samples():
    conn = _get_db_conn()
    rows = conn.execute(
        "SELECT id, session_id, turn, audio_path, features_json, auto_labels_json, human_labels_json, created_at FROM audio_labels ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        result.append({
            "id": row["id"],
            "session_id": row["session_id"],
            "turn": row["turn"],
            "audio_url": f"/audio/samples/{row['session_id']}/{row['turn']}/file",
            "features": json.loads(row["features_json"]),
            "auto_labels": json.loads(row["auto_labels_json"]),
            "human_labels": json.loads(row["human_labels_json"]) if row["human_labels_json"] else None,
            "created_at": row["created_at"],
        })
    return result

@app.post("/audio/label")
def save_audio_label(body: dict):
    session_id = body.get("session_id")
    turn = body.get("turn")
    human_labels = body.get("human_labels")
    if not session_id or turn is None or not human_labels:
        raise HTTPException(status_code=400, detail="session_id, turn, and human_labels required")
    conn = _get_db_conn()
    updated = conn.execute(
        "UPDATE audio_labels SET human_labels_json = ? WHERE session_id = ? AND turn = ?",
        (json.dumps(human_labels), session_id, turn)
    ).rowcount
    conn.commit()
    conn.close()
    if not updated:
        raise HTTPException(status_code=404, detail="Sample not found")
    return {"ok": True}

@app.get("/audio/samples/{session_id}/{turn}/file")
def get_audio_file(session_id: str, turn: int):
    from fastapi.responses import FileResponse
    path = f"audio_samples/{session_id}_{turn}.wav"
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Audio file not found")
    return FileResponse(path, media_type="audio/wav")

@app.post("/audio/samples/upload")
async def upload_baseline_sample(audio_file: UploadFile = File(...)):
    import asyncio
    import uuid as _uuid
    audio_bytes = await audio_file.read()
    session_id = f"baseline_{_uuid.uuid4().hex[:8]}"
    turn = 0
    audio_path = f"audio_samples/{session_id}_{turn}.wav"
    with open(audio_path, 'wb') as fh:
        fh.write(audio_bytes)
    raw_features = await _process_audio_file(audio_bytes)
    # Use full personality analysis (includes few-shot from human-labeled examples)
    loop = asyncio.get_event_loop()
    auto_labels = await loop.run_in_executor(None, lambda: _analyze_audio_personality(raw_features))
    created_at = int(time.time())
    conn = _get_db_conn()
    cur = conn.execute(
        "INSERT INTO audio_labels (session_id, turn, audio_path, features_json, auto_labels_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (session_id, turn, audio_path, json.dumps(raw_features), json.dumps(auto_labels), created_at),
    )
    row_id = cur.lastrowid
    conn.commit()
    conn.close()
    return {
        "id": row_id,
        "session_id": session_id,
        "turn": turn,
        "audio_url": f"/audio/samples/{session_id}/{turn}/file",
        "features": raw_features,
        "auto_labels": auto_labels,
        "human_labels": None,
        "created_at": created_at,
    }
