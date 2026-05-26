"""
Module de transcription vocale — Mistral Voxtral API.
Raccourci global : Ctrl+Alt+R (push-to-talk toggle).
"""

import ctypes
import io
import logging
import sys
import threading
import time
import wave

from pynput import keyboard
from pynput.keyboard import Controller as KBController, Key

# numpy / sounddevice / mistralai sont importes paresseusement (au 1er
# enregistrement) pour garder l'empreinte memoire minimale au lancement.

log = logging.getLogger(__name__)

MODEL = "voxtral-mini-latest"
SAMPLE_RATE = 16000
CHANNELS = 1

# Messages d'etat, ton decontracte, FR + EN. Repli sur "fr" si cle absente.
STRINGS = {
    "fr": {
        "key_missing": "Pas de clé API",
        "mic_not_found": "Micro aux abonnés absents : {e}",
        "mic_error": "Couac micro : {e}",
        "recording": "Je t'écoute...",
        "no_audio": "Rien capté",
        "transcribing": "Je gribouille...",
        "ok_chars": "Et voilà — {n} car.",
        "nothing": "J'ai rien entendu",
        "error": "Aïe : {e}",
        "clipboard_busy": "Presse-papier occupé, réessaie",
    },
    "en": {
        "key_missing": "No API key",
        "mic_not_found": "Mic is MIA: {e}",
        "mic_error": "Mic hiccup: {e}",
        "recording": "I'm all ears...",
        "no_audio": "Caught nothing",
        "transcribing": "Scribbling...",
        "ok_chars": "There you go — {n} chars",
        "nothing": "Heard nothing",
        "error": "Oops: {e}",
        "clipboard_busy": "Clipboard's busy, try again",
    },
}


class VoiceTranscriber:
    """Enregistre au micro, transcrit via Voxtral, colle au curseur."""

    def __init__(self, api_key="", language=None, sound=True,
                 device=None, on_status=None, on_result=None,
                 on_level=None, lang="fr"):
        self.api_key = api_key
        self.language = language   # code ISO ex: "fr", "en", None=auto
        self.lang = lang if lang in STRINGS else "fr"   # langue de l'UI
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
        self._lock = threading.Lock()   # protege recording / stream
        self._restore_timer = None      # Timer de restauration presse-papier

    # ── Device enumeration ─────────────────────────────

    @staticmethod
    def list_input_devices():
        """Retourne [(index, nom)] des peripheriques d'entree disponibles."""
        try:
            import sounddevice as sd
            devices = sd.query_devices()
        except Exception as e:
            log.debug("Enumeration des peripheriques echouee: %s", e)
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
        self._close_stream()
        with self._lock:
            timer = self._restore_timer
        if timer:
            timer.cancel()
        if self._listener:
            self._listener.stop()

    def _close_stream(self):
        """Arrete et ferme le flux d'enregistrement (idempotent, thread-safe).
        Capture le handle sous verrou : evite un double-close si le raccourci
        et la fermeture de l'app surviennent simultanement."""
        with self._lock:
            self.recording = False
            stream, self.stream = self.stream, None
        if stream:
            try:
                stream.stop()
                stream.close()
            except Exception as e:
                log.debug("Fermeture flux echouee: %s", e)

    def update_key(self, key):
        self.api_key = key

    def update_language(self, lang):
        self.language = lang

    def update_device(self, device):
        self.device = device

    # ── Recording ───────────────────────────────────────

    def _toggle(self):
        if not self.api_key:
            self._emit(self._t("key_missing"), False, "error")
            return
        if self.recording:
            self._stop_rec()
        else:
            self._start_rec()

    def _start_rec(self):
        import numpy as np
        import sounddevice as sd

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
            self._emit(self._t("mic_not_found", e=e), False, "error")
            return
        except Exception as e:
            self.stream = None
            self.recording = False
            self._emit(self._t("mic_error", e=e), False, "error")
            return

        self.recording = True
        self._beep(880, 150)
        self._emit(self._t("recording"), True, "rec")

    def _stop_rec(self):
        self._close_stream()
        self._beep(440, 150)

        frames = self.frames
        self.frames = []   # l'enregistrement suivant repart sur une liste propre

        if not frames:
            self._emit(self._t("no_audio"), False, "info")
            return

        self._emit(self._t("transcribing"), False, "busy")
        threading.Thread(
            target=self._process, args=(frames,), daemon=True
        ).start()

    # ── Mic test ────────────────────────────────────────

    def test_mic(self, device=None, duration=1.5, callback=None):
        """Enregistre brievement et detecte si du son est capte."""
        dev = device if device is not None else self.device

        def _run():
            try:
                import numpy as np
                import sounddevice as sd
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
            except Exception as e:
                log.debug("Test micro echoue: %s", e)
                if callback:
                    callback(False, 0.0)

        threading.Thread(target=_run, daemon=True).start()

    # ── Transcription ───────────────────────────────────

    def _process(self, frames):
        import numpy as np
        try:
            audio = np.concatenate(frames)
            wav = self._to_wav(audio)
            text = self._transcribe(wav)
            if text:
                pasted = self._paste(text)
                if self.on_result:
                    self.on_result(text)   # historise meme si le collage echoue
                if pasted:
                    self._emit(self._t("ok_chars", n=len(text)), False, "ok")
                # sinon _paste a deja emis le message d'erreur
            else:
                self._emit(self._t("nothing"), False, "info")
        except Exception as e:
            self._emit(self._t("error", e=e), False, "error")

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
        from mistralai import Mistral
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
        """Colle `text` au curseur via le presse-papier (Ctrl+V), puis
        restaure en arriere-plan le texte precedent. Retourne False si le
        presse-papier etait inaccessible (collage impossible)."""
        previous = self._get_clipboard()
        time.sleep(0.15)
        if not self._set_clipboard(text):
            self._emit(self._t("clipboard_busy"), False, "error")
            return False
        with self._kb.pressed(Key.ctrl):
            self._kb.tap("v")
        if previous is not None:
            # On laisse l'app cible lire le collage avant de restaurer ; en
            # arriere-plan (daemon) pour ne pas retarder le statut ni la sortie.
            timer = threading.Timer(
                0.5, self._restore_clipboard, args=(previous, text)
            )
            timer.daemon = True
            with self._lock:               # une seule restauration en vol
                old, self._restore_timer = self._restore_timer, timer
            if old:
                old.cancel()
            timer.start()
        return True

    def _restore_clipboard(self, previous, pasted):
        # Ne restaure que si le presse-papier contient toujours NOTRE texte :
        # evite d'ecraser une dictee suivante ou une copie faite entre-temps.
        try:
            if self._get_clipboard() == pasted:
                self._set_clipboard(previous)
        except Exception as e:
            log.debug("Restauration presse-papier echouee: %s", e)

    @staticmethod
    def _open_clipboard(u32, tries=6):
        """OpenClipboard avec quelques tentatives : une autre app le verrouille
        souvent brievement juste apres un Ctrl+C/Ctrl+V."""
        for _ in range(tries):
            if u32.OpenClipboard(0):
                return True
            time.sleep(0.02)
        return False

    @classmethod
    def _get_clipboard(cls):
        """Lit le texte du presse-papier (CF_UNICODETEXT), ou None si vide,
        non-texte, ou inaccessible — auquel cas on ne restaurera rien."""
        CF_UNICODETEXT = 13
        u32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32
        u32.GetClipboardData.restype = ctypes.c_void_p
        u32.GetClipboardData.argtypes = (ctypes.c_uint,)
        k32.GlobalLock.restype = ctypes.c_void_p
        k32.GlobalLock.argtypes = (ctypes.c_void_p,)
        k32.GlobalUnlock.argtypes = (ctypes.c_void_p,)
        k32.GlobalSize.restype = ctypes.c_size_t
        k32.GlobalSize.argtypes = (ctypes.c_void_p,)

        if not cls._open_clipboard(u32):
            return None
        try:
            if not u32.IsClipboardFormatAvailable(CF_UNICODETEXT):
                return None
            h = u32.GetClipboardData(CF_UNICODETEXT)
            if not h:
                return None
            n = k32.GlobalSize(h)      # borne la lecture : pas d'over-read
            p = k32.GlobalLock(h)
            if not p:
                return None
            try:
                raw = ctypes.string_at(p, n) if n else b""
            finally:
                k32.GlobalUnlock(h)
            return raw.decode("utf-16-le", "ignore").split("\x00", 1)[0]
        finally:
            u32.CloseClipboard()

    @classmethod
    def _set_clipboard(cls, text):
        """Place `text` sur le presse-papier. Retourne True si reussi."""
        CF_UNICODETEXT = 13
        GMEM_MOVEABLE = 0x0042  # MOVEABLE | ZEROINIT
        u32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32
        # restype/argtypes obligatoires sinon les handles 64-bit sont
        # tronques a 32-bit (corruption / crash sur Python 64-bit).
        k32.GlobalAlloc.restype = ctypes.c_void_p
        k32.GlobalAlloc.argtypes = (ctypes.c_uint, ctypes.c_size_t)
        k32.GlobalLock.restype = ctypes.c_void_p
        k32.GlobalLock.argtypes = (ctypes.c_void_p,)
        k32.GlobalUnlock.argtypes = (ctypes.c_void_p,)
        k32.GlobalFree.restype = ctypes.c_void_p
        k32.GlobalFree.argtypes = (ctypes.c_void_p,)
        u32.SetClipboardData.restype = ctypes.c_void_p
        u32.SetClipboardData.argtypes = (ctypes.c_uint, ctypes.c_void_p)

        if not cls._open_clipboard(u32):
            return False
        h = None
        try:
            u32.EmptyClipboard()
            data = text.encode("utf-16-le") + b"\x00\x00"
            h = k32.GlobalAlloc(GMEM_MOVEABLE, len(data))
            if not h:
                return False
            p = k32.GlobalLock(h)
            if not p:                 # rare ; le finally libere le handle
                return False
            ctypes.memmove(p, data, len(data))
            k32.GlobalUnlock(h)
            if u32.SetClipboardData(CF_UNICODETEXT, h):
                h = None              # ownership transfere au systeme
                return True
            return False
        finally:
            if h:
                k32.GlobalFree(h)
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

    def _t(self, key, **kw):
        s = STRINGS.get(self.lang, STRINGS["fr"]).get(key) \
            or STRINGS["fr"].get(key, key)
        return s.format(**kw) if kw else s

    def _emit(self, msg, is_recording, kind="info"):
        if self.on_status:
            self.on_status(msg, is_recording, kind)
