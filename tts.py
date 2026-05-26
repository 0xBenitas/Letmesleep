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

# Messages d'etat, ton decontracte, FR + EN. Repli sur "fr" si cle absente.
STRINGS = {
    "fr": {
        "no_text": "Rien à lire",
        "key_missing": "Pas de clé API",
        "thinking": "Voxtral cogite...",
        "playing": "Ça cause...",
        "done": "Et voilà !",
        "error": "Aïe : {e}",
        "error_play": "Couac lecture : {e}",
        "stopped": "Coupé",
    },
    "en": {
        "no_text": "Nothing to read",
        "key_missing": "No API key",
        "thinking": "Voxtral is thinking...",
        "playing": "Talking...",
        "done": "There you go!",
        "error": "Oops: {e}",
        "error_play": "Playback hiccup: {e}",
        "stopped": "Stopped",
    },
}

# Voix pre-configurees Mistral : (id, {langue_ui: libelle affiche}).
VOICES = [
    ("neutral_female", {"fr": "Femme neutre", "en": "Neutral female"}),
    ("neutral_male", {"fr": "Homme neutre", "en": "Neutral male"}),
    ("cheerful_female", {"fr": "Femme joyeuse", "en": "Cheerful female"}),
    ("casual_female", {"fr": "Femme décontractée", "en": "Casual female"}),
    ("casual_male", {"fr": "Homme décontracté", "en": "Casual male"}),
    ("fr_female", {"fr": "Français (femme)", "en": "French (female)"}),
    ("fr_male", {"fr": "Français (homme)", "en": "French (male)"}),
    ("es_female", {"fr": "Espagnol (femme)", "en": "Spanish (female)"}),
    ("es_male", {"fr": "Espagnol (homme)", "en": "Spanish (male)"}),
    ("de_female", {"fr": "Allemand (femme)", "en": "German (female)"}),
    ("de_male", {"fr": "Allemand (homme)", "en": "German (male)"}),
    ("it_female", {"fr": "Italien (femme)", "en": "Italian (female)"}),
    ("it_male", {"fr": "Italien (homme)", "en": "Italian (male)"}),
    ("pt_female", {"fr": "Portugais (femme)", "en": "Portuguese (female)"}),
    ("pt_male", {"fr": "Portugais (homme)", "en": "Portuguese (male)"}),
    ("nl_female", {"fr": "Néerlandais (femme)", "en": "Dutch (female)"}),
    ("nl_male", {"fr": "Néerlandais (homme)", "en": "Dutch (male)"}),
    ("hi_female", {"fr": "Hindi (femme)", "en": "Hindi (female)"}),
    ("hi_male", {"fr": "Hindi (homme)", "en": "Hindi (male)"}),
    ("ar_male", {"fr": "Arabe (homme)", "en": "Arabic (male)"}),
]


class TextToSpeechReader:
    """Lit du texte a voix haute via Mistral Voxtral TTS."""

    def __init__(self, api_key="", voice_id="fr_female", on_status=None,
                 lang="fr"):
        self.api_key = api_key
        self.voice_id = voice_id
        self.on_status = on_status
        self.lang = lang if lang in STRINGS else "fr"   # langue de l'UI
        self._thread = None
        self._speaking = False
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._generation = 0   # incremente a chaque speak()/stop()

    @property
    def speaking(self):
        return self._speaking

    def get_voices(self):
        """Retourne [(id, libelle)] dans la langue de l'UI (repli FR)."""
        return [(vid, names.get(self.lang, names["fr"])) for vid, names in VOICES]

    def speak(self, text, voice_id=None):
        """Lance la lecture du texte dans un thread separe."""
        if not text.strip():
            self._emit(self._t("no_text"), False, "info")
            return
        if not self.api_key:
            self._emit(self._t("key_missing"), False, "error")
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
            self._emit_if_current(gen, self._t("thinking"), True, "busy")
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
            self._emit_if_current(gen, self._t("error", e=e), False, "error")
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

        self._emit_if_current(gen, self._t("playing"), True, "rec")
        try:
            sd.play(audio, samplerate=sample_rate)
            # Attendre la fin ou un stop (propre a cette lecture).
            while sd.get_stream().active:
                if stop_event.is_set():
                    # Ne couper le flux partage que si c'est toujours NOTRE
                    # lecture : un worker perime ne doit pas tuer la nouvelle
                    # (stop()/speak() ont deja appele sd.stop() au besoin).
                    if gen == self._generation:
                        sd.stop()
                    return
                stop_event.wait(timeout=0.1)
            self._emit_if_current(gen, self._t("done"), False, "ok")
        except Exception as e:
            self._emit_if_current(gen, self._t("error_play", e=e), False, "error")

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
        self._emit(self._t("stopped"), False, "info")

    def update_key(self, key):
        self.api_key = key

    def update_voice(self, voice_id):
        self.voice_id = voice_id

    def _t(self, key, **kw):
        s = STRINGS.get(self.lang, STRINGS["fr"]).get(key) \
            or STRINGS["fr"].get(key, key)
        return s.format(**kw) if kw else s

    def _emit(self, msg, is_speaking, kind="info"):
        if self.on_status:
            self.on_status(msg, is_speaking, kind)

    def _emit_if_current(self, gen, msg, is_speaking, kind="info"):
        # N'affiche le statut que si la lecture est toujours d'actualite :
        # un thread annule (stop ou nouvelle lecture) ne pollue pas l'UI.
        if gen == self._generation:
            self._emit(msg, is_speaking, kind)
