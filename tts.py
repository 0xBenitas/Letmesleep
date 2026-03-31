"""
Module de lecture vocale (Text-to-Speech) — pyttsx3 / Windows SAPI.
Coller du texte, cliquer sur Lire, et l'entendre.
"""

import threading

import pyttsx3


class TextToSpeechReader:
    """Lit du texte a voix haute via le moteur TTS systeme."""

    def __init__(self, rate=180, volume=1.0, on_status=None):
        self.rate = rate
        self.volume = volume
        self.on_status = on_status
        self._engine = None
        self._thread = None
        self._speaking = False
        self._lock = threading.Lock()

    @property
    def speaking(self):
        return self._speaking

    def get_voices(self):
        """Retourne la liste des voix disponibles [(id, name), ...]."""
        try:
            engine = pyttsx3.init()
            voices = [(v.id, v.name) for v in engine.getProperty("voices")]
            engine.stop()
            return voices
        except Exception:
            return []

    def speak(self, text, voice_id=None):
        """Lance la lecture du texte dans un thread separe."""
        if not text.strip():
            self._emit("Aucun texte", False)
            return
        if self._speaking:
            self.stop()

        self._speaking = True
        self._thread = threading.Thread(
            target=self._run, args=(text, voice_id), daemon=True
        )
        self._thread.start()

    def _run(self, text, voice_id):
        try:
            self._emit("Lecture en cours...", True)
            self._engine = pyttsx3.init()
            self._engine.setProperty("rate", self.rate)
            self._engine.setProperty("volume", self.volume)
            if voice_id:
                self._engine.setProperty("voice", voice_id)
            self._engine.say(text)
            self._engine.runAndWait()
            if self._speaking:
                self._emit("Lecture terminee", False)
        except Exception as e:
            self._emit(f"Erreur: {e}", False)
        finally:
            with self._lock:
                self._speaking = False
                self._engine = None

    def stop(self):
        """Arrete la lecture en cours."""
        with self._lock:
            self._speaking = False
            if self._engine:
                try:
                    self._engine.stop()
                except Exception:
                    pass
                self._engine = None
        self._emit("Arrete", False)

    def update_rate(self, rate):
        self.rate = rate

    def update_volume(self, volume):
        self.volume = volume

    def _emit(self, msg, is_speaking):
        if self.on_status:
            self.on_status(msg, is_speaking)
