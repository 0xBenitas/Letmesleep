"""
Module de lecture vocale (Text-to-Speech) — Mistral Voxtral TTS API.
Coller du texte, cliquer sur Lire, et l'entendre.
"""

import base64
import io
import threading
import wave

import numpy as np
import sounddevice as sd
from mistralai import Mistral

MODEL = "voxtral-mini-tts-2603"

# Voix pre-configurees disponibles via l'API Mistral
VOICES = [
    ("Femme neutre", "neutral_female"),
    ("Homme neutre", "neutral_male"),
    ("Femme joyeuse", "cheerful_female"),
    ("Femme decontractee", "casual_female"),
    ("Homme decontracte", "casual_male"),
    ("Francais (femme)", "fr_female"),
    ("Francais (homme)", "fr_male"),
    ("Espagnol (femme)", "es_female"),
    ("Espagnol (homme)", "es_male"),
    ("Allemand (femme)", "de_female"),
    ("Allemand (homme)", "de_male"),
    ("Italien (femme)", "it_female"),
    ("Italien (homme)", "it_male"),
    ("Portugais (femme)", "pt_female"),
    ("Portugais (homme)", "pt_male"),
    ("Neerlandais (femme)", "nl_female"),
    ("Neerlandais (homme)", "nl_male"),
    ("Hindi (femme)", "hi_female"),
    ("Hindi (homme)", "hi_male"),
    ("Arabe (homme)", "ar_male"),
]


class TextToSpeechReader:
    """Lit du texte a voix haute via Mistral Voxtral TTS."""

    def __init__(self, api_key="", voice_id="fr_female", on_status=None):
        self.api_key = api_key
        self.voice_id = voice_id
        self.on_status = on_status
        self._thread = None
        self._speaking = False
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

    @property
    def speaking(self):
        return self._speaking

    @staticmethod
    def get_voices():
        """Retourne la liste des voix disponibles [(id, name), ...]."""
        return [(vid, name) for name, vid in VOICES]

    def speak(self, text, voice_id=None):
        """Lance la lecture du texte dans un thread separe."""
        if not text.strip():
            self._emit("Aucun texte", False)
            return
        if not self.api_key:
            self._emit("Cle API manquante", False)
            return
        if self._speaking:
            self.stop()

        self._stop_event.clear()
        self._speaking = True
        vid = voice_id or self.voice_id
        self._thread = threading.Thread(
            target=self._run, args=(text, vid), daemon=True
        )
        self._thread.start()

    def _run(self, text, voice_id):
        try:
            self._emit("Voxtral reflechit...", True)
            client = Mistral(api_key=self.api_key, timeout_ms=30000)
            response = client.audio.speech.complete(
                model=MODEL,
                input=text,
                voice_id=voice_id,
                response_format="wav",
            )
            if self._stop_event.is_set():
                return

            audio_bytes = base64.b64decode(response.audio_data)
            self._play_wav(audio_bytes)

        except Exception as e:
            self._emit(f"Erreur: {e}", False)
        finally:
            with self._lock:
                self._speaking = False

    def _play_wav(self, wav_bytes):
        """Decode et joue un fichier WAV via sounddevice."""
        buf = io.BytesIO(wav_bytes)
        with wave.open(buf, "rb") as wf:
            sample_rate = wf.getframerate()
            n_channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            raw = wf.readframes(wf.getnframes())

        if sample_width == 2:
            dtype = np.int16
        elif sample_width == 4:
            dtype = np.int32
        else:
            dtype = np.float32

        audio = np.frombuffer(raw, dtype=dtype)
        if n_channels > 1:
            audio = audio.reshape(-1, n_channels)

        if self._stop_event.is_set():
            return

        self._emit("Lecture en cours...", True)
        try:
            sd.play(audio, samplerate=sample_rate)
            # Attendre la fin ou un stop
            while sd.get_stream().active:
                if self._stop_event.is_set():
                    sd.stop()
                    self._emit("Arrete", False)
                    return
                self._stop_event.wait(timeout=0.1)
            self._emit("Fini !", False)
        except Exception as e:
            self._emit(f"Erreur lecture: {e}", False)

    def stop(self):
        """Arrete la lecture en cours."""
        self._stop_event.set()
        with self._lock:
            self._speaking = False
        try:
            sd.stop()
        except Exception:
            pass
        self._emit("Stop", False)

    def update_key(self, key):
        self.api_key = key

    def update_voice(self, voice_id):
        self.voice_id = voice_id

    def _emit(self, msg, is_speaking):
        if self.on_status:
            self.on_status(msg, is_speaking)
