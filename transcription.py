"""
Module de transcription vocale — Mistral Voxtral API.
Raccourci global : Ctrl+Alt+R (push-to-talk toggle).
"""

import ctypes
import io
import threading
import time
import wave

import numpy as np
import sounddevice as sd
from mistralai import Mistral
from pynput import keyboard
from pynput.keyboard import Controller as KBController, Key

MODEL = "voxtral-mini-latest"
SAMPLE_RATE = 16000
CHANNELS = 1


class VoiceTranscriber:
    """Enregistre au micro, transcrit via Voxtral, colle au curseur."""

    def __init__(self, api_key="", on_status=None):
        self.api_key = api_key
        self.recording = False
        self.frames = []
        self.stream = None
        self.on_status = on_status  # callback(msg: str, is_recording: bool)
        self._kb = KBController()
        self._listener = None
        self.running = False

    # ── Lifecycle ───────────────────────────────────────

    def start(self):
        """Commence a ecouter le raccourci global."""
        self.running = True
        self._listener = keyboard.GlobalHotKeys(
            {"<ctrl>+<alt>+r": self._toggle}
        )
        self._listener.start()

    def stop(self):
        self.running = False
        if self.recording:
            self.recording = False
            if self.stream:
                self.stream.stop()
                self.stream.close()
        if self._listener:
            self._listener.stop()

    def update_key(self, key):
        self.api_key = key

    # ── Recording ───────────────────────────────────────

    def _toggle(self):
        if not self.api_key:
            self._emit("Cle API manquante", False)
            return
        if self.recording:
            self._stop_rec()
        else:
            self._start_rec()

    def _start_rec(self):
        self.recording = True
        self.frames = []
        self._emit("Enregistrement...", True)

        def cb(indata, frames, t, status):
            if self.recording:
                self.frames.append(indata.copy())

        self.stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            callback=cb,
        )
        self.stream.start()

    def _stop_rec(self):
        self.recording = False
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None

        if not self.frames:
            self._emit("Aucun audio capture", False)
            return

        self._emit("Transcription...", False)
        threading.Thread(target=self._process, daemon=True).start()

    # ── Transcription ───────────────────────────────────

    def _process(self):
        try:
            audio = np.concatenate(self.frames)
            wav = self._to_wav(audio)
            text = self._transcribe(wav)
            if text:
                self._paste(text)
                n = len(text)
                self._emit(f"OK — {n} car.", False)
            else:
                self._emit("Rien detecte", False)
        except Exception as e:
            self._emit(f"Erreur: {e}", False)

    @staticmethod
    def _to_wav(audio):
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(CHANNELS)
            w.setsampwidth(2)  # 16-bit
            w.setframerate(SAMPLE_RATE)
            w.writeframes(audio.tobytes())
        buf.seek(0)
        return buf

    def _transcribe(self, wav_buf):
        client = Mistral(api_key=self.api_key)
        resp = client.audio.transcriptions.complete(
            model=MODEL,
            file={"content": wav_buf, "file_name": "recording.wav"},
        )
        return resp.text.strip() if resp.text else ""

    # ── Paste at cursor ─────────────────────────────────

    def _paste(self, text):
        """Copie dans le presse-papier puis Ctrl+V."""
        time.sleep(0.15)
        self._set_clipboard(text)
        with self._kb.pressed(Key.ctrl):
            self._kb.tap("v")

    @staticmethod
    def _set_clipboard(text):
        CF_UNICODETEXT = 13
        u32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32
        u32.OpenClipboard(0)
        u32.EmptyClipboard()
        data = text.encode("utf-16-le") + b"\x00\x00"
        h = k32.GlobalAlloc(0x0042, len(data))
        p = k32.GlobalLock(h)
        ctypes.memmove(p, data, len(data))
        k32.GlobalUnlock(h)
        u32.SetClipboardData(CF_UNICODETEXT, h)
        u32.CloseClipboard()

    # ── Helpers ─────────────────────────────────────────

    def _emit(self, msg, is_recording):
        if self.on_status:
            self.on_status(msg, is_recording)
