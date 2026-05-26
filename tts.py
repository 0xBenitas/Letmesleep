"""
Module de lecture vocale (Text-to-Speech) — Mistral Voxtral TTS API.
Coller du texte, cliquer sur Lire, et l'entendre.
"""

import base64
import io
import logging
import threading
import wave

# numpy / sounddevice / mistralai sont importes paresseusement (au 1er
# "Lire") pour ne rien charger en memoire tant que le TTS n'est pas utilise.

log = logging.getLogger(__name__)

MODEL = "voxtral-mini-tts-2603"

# Voix pre-configurees disponibles via l'API Mistral
VOICES = [
    ("Femme neutre", "neutral_female"),
    ("Homme neutre", "neutral_male"),
    ("Femme joyeuse", "cheerful_female"),
    ("Femme décontractée", "casual_female"),
    ("Homme décontracté", "casual_male"),
    ("Français (femme)", "fr_female"),
    ("Français (homme)", "fr_male"),
    ("Espagnol (femme)", "es_female"),
    ("Espagnol (homme)", "es_male"),
    ("Allemand (femme)", "de_female"),
    ("Allemand (homme)", "de_male"),
    ("Italien (femme)", "it_female"),
    ("Italien (homme)", "it_male"),
    ("Portugais (femme)", "pt_female"),
    ("Portugais (homme)", "pt_male"),
    ("Néerlandais (femme)", "nl_female"),
    ("Néerlandais (homme)", "nl_male"),
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
        self._generation = 0   # incremente a chaque speak()/stop()

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
            self._emit("Clé API manquante", False)
            return

        # Nouvelle generation : on signale l'ancien event (le thread en cours
        # le voit et s'arrete) et on en cree un neuf pour cette lecture. Pas
        # de .clear() partage, donc aucun risque que l'ancien thread reparte.
        with self._lock:
            self._generation += 1
            gen = self._generation
            self._stop_event.set()
            self._stop_event = threading.Event()
            stop_event = self._stop_event
            self._speaking = True

        # Coupe immediatement le son d'une eventuelle lecture precedente.
        try:
            import sounddevice as sd
            sd.stop()
        except Exception as e:
            log.debug("Arret lecture echoue: %s", e)

        vid = voice_id or self.voice_id
        self._thread = threading.Thread(
            target=self._run, args=(text, vid, gen, stop_event), daemon=True
        )
        self._thread.start()

    def _run(self, text, voice_id, gen, stop_event):
        try:
            from mistralai import Mistral
            self._emit_if_current(gen, "Voxtral réfléchit...", True)
            client = Mistral(api_key=self.api_key, timeout_ms=30000)
            response = client.audio.speech.complete(
                model=MODEL,
                input=text,
                voice_id=voice_id,
                response_format="wav",
            )
            if stop_event.is_set():
                return

            audio_bytes = base64.b64decode(response.audio_data)
            self._play_wav(audio_bytes, gen, stop_event)

        except Exception as e:
            self._emit_if_current(gen, f"Erreur: {e}", False)
        finally:
            with self._lock:
                if gen == self._generation:
                    self._speaking = False

    def _play_wav(self, wav_bytes, gen, stop_event):
        """Decode et joue un fichier WAV via sounddevice."""
        import numpy as np
        import sounddevice as sd

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

        if stop_event.is_set():
            return

        self._emit_if_current(gen, "Lecture en cours...", True)
        try:
            sd.play(audio, samplerate=sample_rate)
            # Attendre la fin ou un stop (propre a cette lecture).
            while sd.get_stream().active:
                if stop_event.is_set():
                    sd.stop()
                    return  # l'arret est annonce par stop()/speak()
                stop_event.wait(timeout=0.1)
            self._emit_if_current(gen, "Fini !", False)
        except Exception as e:
            self._emit_if_current(gen, f"Erreur lecture: {e}", False)

    def stop(self):
        """Arrete la lecture en cours."""
        with self._lock:
            self._generation += 1   # invalide la lecture courante
            self._stop_event.set()
            self._speaking = False
        try:
            import sounddevice as sd
            sd.stop()
        except Exception as e:
            log.debug("Arret lecture echoue: %s", e)
        self._emit("Stop", False)

    def update_key(self, key):
        self.api_key = key

    def update_voice(self, voice_id):
        self.voice_id = voice_id

    def _emit(self, msg, is_speaking):
        if self.on_status:
            self.on_status(msg, is_speaking)

    def _emit_if_current(self, gen, msg, is_speaking):
        # N'affiche le statut que si la lecture est toujours d'actualite :
        # un thread annule (stop ou nouvelle lecture) ne pollue pas l'UI.
        if gen == self._generation:
            self._emit(msg, is_speaking)
