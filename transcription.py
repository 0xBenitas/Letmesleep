"""
Module de transcription vocale — Mistral Voxtral API.
Raccourci global : Ctrl+Alt+R (push-to-talk toggle).
"""

import ctypes
import io
import sys
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

    def __init__(self, api_key="", language=None, sound=True,
                 device=None, on_status=None, on_result=None,
                 on_level=None):
        self.api_key = api_key
        self.language = language   # code ISO ex: "fr", "en", None=auto
        self.sound = sound
        self.device = device       # index sounddevice, None = defaut systeme
        self.recording = False
        self.frames = []
        self.stream = None
        self.on_status = on_status    # callback(msg: str, is_recording: bool)
        self.on_result = on_result    # callback(text: str)
        self._on_level = on_level     # callback(peak: float 0.0-1.0)
        self._level_counter = 0       # throttle level callbacks
        self._kb = KBController()
        self._listener = None
        self.running = False

    # ── Device enumeration ─────────────────────────────

    @staticmethod
    def list_input_devices():
        """Retourne [(index, nom)] des peripheriques d'entree disponibles."""
        try:
            devices = sd.query_devices()
        except Exception:
            return []
        result = []
        for i, dev in enumerate(devices):
            if dev['max_input_channels'] > 0:
                result.append((i, dev['name']))
        return result

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
                self.stream = None
        if self._listener:
            self._listener.stop()

    def update_key(self, key):
        self.api_key = key

    def update_language(self, lang):
        self.language = lang

    def update_device(self, device):
        self.device = device

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
        self.frames = []
        self._level_counter = 0

        def cb(indata, frames, t, status):
            if self.recording:
                self.frames.append(indata.copy())
                if self._on_level:
                    self._level_counter += 1
                    if self._level_counter % 4 == 0:
                        peak = np.max(np.abs(indata)) / 32768.0
                        self._on_level(peak)

        try:
            self.stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                callback=cb,
                device=self.device,
            )
            self.stream.start()
        except sd.PortAudioError as e:
            self.stream = None
            self.recording = False
            self._emit(f"Micro introuvable: {e}", False)
            return
        except Exception as e:
            self.stream = None
            self.recording = False
            self._emit(f"Erreur micro: {e}", False)
            return

        self.recording = True
        self._beep(880, 150)
        self._emit("Enregistrement...", True)

    def _stop_rec(self):
        self.recording = False
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None

        self._beep(440, 150)

        if not self.frames:
            self._emit("Aucun audio capture", False)
            return

        self._emit("Transcription...", False)
        threading.Thread(target=self._process, daemon=True).start()

    # ── Mic test ────────────────────────────────────────

    def test_mic(self, device=None, duration=1.5, callback=None):
        """Enregistre brievement et detecte si du son est capte."""
        dev = device if device is not None else self.device

        def _run():
            try:
                audio = sd.rec(
                    int(SAMPLE_RATE * duration),
                    samplerate=SAMPLE_RATE,
                    channels=CHANNELS,
                    dtype="int16",
                    device=dev,
                )
                sd.wait()
                peak = np.max(np.abs(audio)) / 32768.0
                if callback:
                    callback(peak > 0.01, peak)
            except Exception:
                if callback:
                    callback(False, 0.0)

        threading.Thread(target=_run, daemon=True).start()

    # ── Transcription ───────────────────────────────────

    def _process(self):
        try:
            audio = np.concatenate(self.frames)
            wav = self._to_wav(audio)
            text = self._transcribe(wav)
            if text:
                self._paste(text)
                if self.on_result:
                    self.on_result(text)
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
        client = Mistral(api_key=self.api_key, timeout_ms=30000)
        kwargs = {
            "model": MODEL,
            "file": {"content": wav_buf, "file_name": "recording.wav"},
        }
        if self.language:
            kwargs["language"] = self.language
        resp = client.audio.transcriptions.complete(**kwargs)
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
        if not u32.OpenClipboard(0):
            return
        try:
            u32.EmptyClipboard()
            data = text.encode("utf-16-le") + b"\x00\x00"
            h = k32.GlobalAlloc(0x0042, len(data))
            p = k32.GlobalLock(h)
            ctypes.memmove(p, data, len(data))
            k32.GlobalUnlock(h)
            u32.SetClipboardData(CF_UNICODETEXT, h)
        finally:
            u32.CloseClipboard()

    # ── Helpers ─────────────────────────────────────────

    def _beep(self, freq, duration):
        if not self.sound:
            return
        if sys.platform == "win32":
            import winsound
            threading.Thread(
                target=lambda: winsound.Beep(freq, duration), daemon=True
            ).start()

    def _emit(self, msg, is_recording):
        if self.on_status:
            self.on_status(msg, is_recording)
