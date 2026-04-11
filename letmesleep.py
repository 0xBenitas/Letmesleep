"""
LetMeSleep — Anti-veille + Transcription vocale + Lecture vocale (TTS).
Conçu pour tourner en arrière-plan sur un PC pro.
"""

import ctypes
import json
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk
from datetime import datetime, timedelta

try:
    from transcription import VoiceTranscriber
    HAS_TRANSCRIPTION = True
except ImportError:
    HAS_TRANSCRIPTION = False

try:
    from tts import TextToSpeechReader, VOICES as TTS_VOICES
    HAS_TTS = True
except ImportError:
    HAS_TTS = False
    TTS_VOICES = []

try:
    import pystray
    from PIL import Image as PILImage
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False


# ── Windows API (déplacement souris) ──────────────────
INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_ulong),
        ("mi", MOUSEINPUT),
    ]


def move_mouse(dx, dy):
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.mi.dx = dx
    inp.mi.dy = dy
    inp.mi.dwFlags = MOUSEEVENTF_MOVE
    inp.mi.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002


def keep_awake(on=True):
    if on:
        ctypes.windll.kernel32.SetThreadExecutionState(
            ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
        )
    else:
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)


# ── Chemins & Config ──────────────────────────────────

def resource_path(relative_path):
    """Résout le chemin vers une ressource, compatible PyInstaller."""
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)


def config_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


CONFIG_FILE = os.path.join(config_dir(), "config.json")


def load_config():
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_config(data):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── Constantes ────────────────────────────────────────

DIRECTIONS = [(1, 0), (0, 1), (-1, 0), (0, -1)]

LANGUAGES = [
    ("Auto", ""),
    ("Français", "fr"),
    ("English", "en"),
    ("Español", "es"),
    ("Deutsch", "de"),
    ("Italiano", "it"),
    ("Português", "pt"),
    ("中文", "zh"),
    ("日本語", "ja"),
    ("한국어", "ko"),
    ("العربية", "ar"),
    ("हिन्दी", "hi"),
    ("Русский", "ru"),
    ("Nederlands", "nl"),
]

LANG_MAP = {name: code for name, code in LANGUAGES}


# ── App ───────────────────────────────────────────────

class LetMeSleep:
    def __init__(self):
        self.active = False
        self.running = True
        self.interval = 30
        self.distance = 5
        self.step = 0
        self.started_at = None
        self.moves = 0
        self.stop_time = None
        self.config = load_config()
        self.transcriber = None
        self.tray_icon = None
        self.history = self.config.get("history", [])

        self.tts_reader = None
        self._tts_voice_ids = []

        self._build_ui()
        self._start_worker()
        self._tick_footer()
        self._tick_timer()
        self._init_transcription()
        self._init_tts()
        self._init_tray()
        self.root.mainloop()

    # ── Palette ────────────────────────────────────────
    BG      = "#1e1e2e"
    CARD    = "#282840"
    TXT     = "#cdd6f4"
    SUB     = "#6c7086"
    GREEN   = "#a6e3a1"
    RED     = "#f38ba8"
    ACCENT  = "#cba6f7"
    PINK    = "#f5c2e7"
    BORDER  = "#45475a"
    SURFACE = "#313244"

    # ── UI ─────────────────────────────────────────────

    def _build_ui(self):
        self.root = tk.Tk()
        self.root.title("LetMeSleep")
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        ico = resource_path("images_transparent.ico")
        if os.path.exists(ico):
            try:
                self.root.iconbitmap(ico)
            except tk.TclError:
                pass

        w, h = 380, 540
        sx = self.root.winfo_screenwidth() - w - 20
        sy = self.root.winfo_screenheight() - h - 60
        self.root.geometry(f"{w}x{h}+{sx}+{sy}")
        self.root.configure(bg=self.BG)

        self._apply_ttk_style()
        self._build_header()

        # ── Notebook (volets) ──
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=(0, 6))

        tab1 = tk.Frame(self.notebook, bg=self.BG)
        tab2 = tk.Frame(self.notebook, bg=self.BG)
        tab3 = tk.Frame(self.notebook, bg=self.BG)
        tab4 = tk.Frame(self.notebook, bg=self.BG)
        self.notebook.add(tab1, text="  Veille  ")
        self.notebook.add(tab2, text="  Dictee  ")
        self.notebook.add(tab3, text="  Parler  ")
        self.notebook.add(tab4, text="  Config  ")

        self._build_tab_antiveille(tab1)
        self._build_tab_transcription(tab2)
        self._build_tab_tts(tab3)
        self._build_tab_settings(tab4)

    def _apply_ttk_style(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure("TNotebook", background=self.BG, borderwidth=0,
                     tabmargins=[4, 4, 4, 0])
        s.configure("TNotebook.Tab", background=self.CARD, foreground=self.SUB,
                     padding=[14, 6], font=("Segoe UI", 9, "bold"), borderwidth=0)
        s.map("TNotebook.Tab",
              background=[("selected", self.SURFACE)],
              foreground=[("selected", self.PINK)])
        s.configure("TCheckbutton", background=self.CARD, foreground=self.TXT,
                     font=("Segoe UI", 9), focuscolor=self.CARD)
        s.map("TCheckbutton", background=[("active", self.CARD)])
        s.configure("TCombobox", fieldbackground=self.SURFACE, foreground=self.TXT,
                     background=self.CARD, arrowcolor=self.PINK)

    def _build_header(self):
        head = tk.Frame(self.root, bg=self.BG)
        head.pack(fill="x", padx=16, pady=(12, 2))

        self.logo_img = None
        png = resource_path("images_transparent.png")
        if os.path.exists(png):
            try:
                self.logo_img = tk.PhotoImage(file=png)
                factor = max(1, self.logo_img.width() // 32)
                self.logo_img = self.logo_img.subsample(factor, factor)
                tk.Label(head, image=self.logo_img, bg=self.BG).pack(side="left", padx=(0, 8))
            except tk.TclError:
                pass

        tk.Label(head, text="LetMeSleep", font=("Segoe UI", 14, "bold"),
                 bg=self.BG, fg=self.PINK).pack(side="left")

        self.status_dot = tk.Label(head, text="●", font=("Segoe UI", 12),
                                    bg=self.BG, fg=self.RED)
        self.status_dot.pack(side="right")
        self.status_lbl = tk.Label(head, text="OFF", font=("Segoe UI", 9),
                                    bg=self.BG, fg=self.SUB)
        self.status_lbl.pack(side="right", padx=(0, 4))

        tk.Label(self.root, text="Ton PC ne dormira plus jamais.",
                 font=("Segoe UI", 8), bg=self.BG, fg=self.SUB
                 ).pack(anchor="w", padx=16, pady=(0, 6))

    # ── Tab: Anti-Veille ───────────────────────────────

    def _build_tab_antiveille(self, parent):
        # Réglages
        card = self._card(parent, top_pad=8)

        row1 = self._row(card)
        self._lbl(row1, "Intervalle")
        self.interval_var = tk.StringVar(value="30")
        self._spinbox(row1, self.interval_var, 5, 300, 5)
        self._lbl(row1, "sec", side="right", pad=(0, 4))

        row2 = self._row(card, pad_top=2, pad_bot=10)
        self._lbl(row2, "Distance")
        self.distance_var = tk.StringVar(value="5")
        self._spinbox(row2, self.distance_var, 1, 50, 1)
        self._lbl(row2, "px", side="right", pad=(0, 4))

        # Timer
        timer = self._card(parent, top_pad=0)
        tk.Label(timer, text="Minuterie", font=("Segoe UI", 9, "bold"),
                 bg=self.CARD, fg=self.TXT).pack(anchor="w", padx=12, pady=(8, 2))

        rt = self._row(timer, pad_bot=4)
        self._lbl(rt, "Couper a")
        self.timer_hour = tk.StringVar(value="")
        self.timer_min = tk.StringVar(value="")
        tf = tk.Frame(rt, bg=self.CARD)
        tf.pack(side="right")
        self._spinbox_in(tf, self.timer_hour, 0, 23, 1, 3, fmt="%02.0f")
        tk.Label(tf, text="h", font=("Segoe UI", 9, "bold"),
                 bg=self.CARD, fg=self.PINK).pack(side="left", padx=2)
        self._spinbox_in(tf, self.timer_min, 0, 59, 5, 3, fmt="%02.0f")

        self.timer_lbl = tk.Label(timer, text="", font=("Segoe UI", 8),
                                   bg=self.CARD, fg=self.SUB)
        self.timer_lbl.pack(pady=(0, 6))

        # Bouton toggle
        self.btn = tk.Button(
            parent, text="▶  Lancer", font=("Segoe UI", 11, "bold"),
            bg=self.ACCENT, fg="#1e1e2e", activebackground=self.ACCENT,
            activeforeground="#1e1e2e", relief="flat", cursor="hand2",
            command=self._toggle, height=1, bd=0,
        )
        self.btn.pack(fill="x", padx=8, pady=(6, 4))

        self.footer = tk.Label(parent, text="En attente... zzz", font=("Segoe UI", 8),
                                bg=self.BG, fg=self.SUB)
        self.footer.pack(pady=(2, 4))

    # ── Tab: Transcription ─────────────────────────────

    def _build_tab_transcription(self, parent):
        # ── Card Micro ──
        card_mic = self._card(parent, top_pad=8)
        tk.Label(card_mic, text="Microphone", font=("Segoe UI", 9, "bold"),
                 bg=self.CARD, fg=self.TXT).pack(anchor="w", padx=12, pady=(6, 2))

        r_mic = self._row(card_mic, pad_top=2, pad_bot=2)
        self._lbl(r_mic, "Micro")
        self.mic_var = tk.StringVar()
        self.mic_combo = ttk.Combobox(r_mic, textvariable=self.mic_var, width=20,
                                       state="readonly", font=("Segoe UI", 8))
        self.mic_combo.pack(side="right")
        self.mic_combo.bind("<<ComboboxSelected>>", self._on_mic_selected)
        self._mic_devices = []

        r_test = self._row(card_mic, pad_top=2, pad_bot=2)
        self._lbl(r_test, "Test")
        self.test_level = tk.Canvas(r_test, width=80, height=12,
                                     bg=self.SURFACE, highlightthickness=0)
        self.test_level.pack(side="right")
        self._small_btn(r_test, "Tester", self._test_mic, side="right", padx=4)

        self.mic_status = tk.Label(card_mic, text="Detection...",
                                    font=("Segoe UI", 8), bg=self.CARD, fg=self.SUB)
        self.mic_status.pack(pady=(0, 6))

        # ── Card Transcription ──
        card_trans = self._card(parent, top_pad=0)

        r1 = self._row(card_trans)
        self._lbl(r1, "Cle Mistral")
        self.api_key_var = tk.StringVar(value=self.config.get("mistral_api_key", ""))
        tk.Entry(r1, textvariable=self.api_key_var, show="\u2022", width=22,
                 font=("Segoe UI", 8), bg=self.SURFACE, fg=self.TXT,
                 relief="flat", insertbackground=self.TXT).pack(side="right")

        r2 = self._row(card_trans, pad_top=2)
        self._lbl(r2, "Langue")
        self.lang_var = tk.StringVar(value=self.config.get("language", "Auto"))
        ttk.Combobox(r2, textvariable=self.lang_var, width=14,
                     values=[l[0] for l in LANGUAGES], state="readonly",
                     font=("Segoe UI", 8)).pack(side="right")

        r3 = self._row(card_trans, pad_top=2, pad_bot=2)
        self._lbl(r3, "Raccourci")
        tk.Label(r3, text="Ctrl+Alt+R", font=("Segoe UI", 9, "bold"),
                 bg=self.CARD, fg=self.PINK).pack(side="right")

        self.trans_status = tk.Label(
            card_trans,
            text="Pret — Ctrl+Alt+R pour dicter" if HAS_TRANSCRIPTION else "Modules manquants (voir README)",
            font=("Segoe UI", 8), bg=self.CARD,
            fg=self.SUB if HAS_TRANSCRIPTION else self.RED,
        )
        self.trans_status.pack(pady=(2, 2))

        self.rec_level = tk.Canvas(card_trans, height=6,
                                    bg=self.SURFACE, highlightthickness=0)
        self.rec_level.pack(fill="x", padx=12, pady=(0, 6))

        # ── Card Historique ──
        hist = self._card(parent, top_pad=0)
        tk.Label(hist, text="Historique", font=("Segoe UI", 9, "bold"),
                 bg=self.CARD, fg=self.TXT).pack(anchor="w", padx=12, pady=(6, 2))

        self.history_list = tk.Listbox(
            hist, bg=self.SURFACE, fg=self.TXT, selectbackground=self.PINK,
            selectforeground="#1e1e2e", font=("Segoe UI", 8),
            relief="flat", borderwidth=0, highlightthickness=0, height=3,
        )
        self.history_list.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        self._refresh_history()

        btn_row = tk.Frame(hist, bg=self.CARD)
        btn_row.pack(fill="x", padx=8, pady=(0, 6))
        self._small_btn(btn_row, "Copier", self._copy_history_item, side="left")
        self._small_btn(btn_row, "Effacer", self._clear_history, side="left", padx=4)

    # ── Tab: Lecture vocale (TTS) ─────────────────────

    def _build_tab_tts(self, parent):
        card = self._card(parent, top_pad=8)

        # Voix
        r1 = self._row(card, pad_top=2, pad_bot=8)
        self._lbl(r1, "Voix")
        self.tts_voice_var = tk.StringVar()
        self.tts_voice_combo = ttk.Combobox(
            r1, textvariable=self.tts_voice_var, width=22,
            state="readonly", font=("Segoe UI", 8),
        )
        self.tts_voice_combo.pack(side="right")

        # Zone de texte
        text_card = self._card(parent, top_pad=0)
        tk.Label(text_card, text="Quoi dire ?", font=("Segoe UI", 9, "bold"),
                 bg=self.CARD, fg=self.TXT).pack(anchor="w", padx=12, pady=(8, 2))

        self.tts_text = tk.Text(
            text_card, bg=self.SURFACE, fg=self.TXT, font=("Segoe UI", 9),
            relief="flat", borderwidth=0, highlightthickness=0,
            height=6, wrap="word", insertbackground=self.TXT,
        )
        self.tts_text.pack(fill="both", expand=True, padx=8, pady=(0, 4))

        # Boutons + status
        btn_row = tk.Frame(text_card, bg=self.CARD)
        btn_row.pack(fill="x", padx=8, pady=(0, 8))

        self.tts_play_btn = tk.Button(
            btn_row, text="▶  Lire", font=("Segoe UI", 9, "bold"),
            bg=self.ACCENT, fg="#1e1e2e", activebackground=self.ACCENT,
            activeforeground="#1e1e2e", relief="flat", cursor="hand2",
            command=self._tts_play, bd=0, padx=12, pady=3,
        )
        self.tts_play_btn.pack(side="left")

        tk.Button(
            btn_row, text="⏹  Stop", font=("Segoe UI", 9, "bold"),
            bg=self.SURFACE, fg=self.TXT, activebackground=self.BORDER,
            activeforeground=self.TXT, relief="flat", cursor="hand2",
            command=self._tts_stop, bd=0, padx=12, pady=3,
        ).pack(side="left", padx=(4, 0))

        self._small_btn(btn_row, "Effacer", self._tts_clear, side="right")
        self._small_btn(btn_row, "Coller", self._tts_paste, side="right", padx=4)

        self.tts_status = tk.Label(
            text_card,
            text="Pret" if HAS_TTS else "Module TTS indisponible",
            font=("Segoe UI", 8), bg=self.CARD,
            fg=self.SUB if HAS_TTS else self.RED,
        )
        self.tts_status.pack(pady=(0, 6))

    # ── Tab: Réglages ──────────────────────────────────

    def _build_tab_settings(self, parent):
        card = self._card(parent, top_pad=8)

        self.autostart_var = tk.BooleanVar(value=self.config.get("autostart", False))
        ttk.Checkbutton(card, text="  Lancer au demarrage",
                        variable=self.autostart_var, command=self._toggle_autostart
                        ).pack(anchor="w", padx=12, pady=(10, 2))

        self.tray_var = tk.BooleanVar(
            value=self.config.get("minimize_to_tray", False) and HAS_TRAY
        )
        cb_tray = ttk.Checkbutton(card, text="  Planquer dans le tray",
                                   variable=self.tray_var)
        cb_tray.pack(anchor="w", padx=12, pady=(2, 2))
        if not HAS_TRAY:
            cb_tray.configure(state="disabled")

        self.sound_var = tk.BooleanVar(value=self.config.get("sound_feedback", True))
        ttk.Checkbutton(card, text="  Bip sonore",
                        variable=self.sound_var
                        ).pack(anchor="w", padx=12, pady=(2, 2))

        self.topmost_var = tk.BooleanVar(value=self.config.get("always_on_top", True))
        ttk.Checkbutton(card, text="  Toujours devant",
                        variable=self.topmost_var, command=self._toggle_topmost
                        ).pack(anchor="w", padx=12, pady=(2, 10))

        # À propos
        about = self._card(parent, top_pad=0)
        tk.Label(about, text="A propos", font=("Segoe UI", 9, "bold"),
                 bg=self.CARD, fg=self.TXT).pack(anchor="w", padx=12, pady=(8, 2))
        tk.Label(about, text="LetMeSleep v3.0", font=("Segoe UI", 10, "bold"),
                 bg=self.CARD, fg=self.PINK).pack(anchor="w", padx=12, pady=(0, 2))
        tk.Label(about,
                 text="Anti-veille pour PC pro qui veulent dormir.\n"
                      "Dictee + lecture vocale par Mistral Voxtral.\n"
                      "Simple. Efficace. Discret.",
                 font=("Segoe UI", 8), bg=self.CARD, fg=self.SUB, justify="left",
                 ).pack(anchor="w", padx=12, pady=(0, 10))

    # ── UI helpers ─────────────────────────────────────

    def _card(self, parent, top_pad=4):
        f = tk.Frame(parent, bg=self.CARD,
                     highlightbackground=self.BORDER, highlightthickness=1)
        f.pack(fill="x", padx=8, pady=(top_pad, 4))
        return f

    def _row(self, parent, pad_top=4, pad_bot=2):
        r = tk.Frame(parent, bg=self.CARD)
        r.pack(fill="x", padx=12, pady=(pad_top, pad_bot))
        return r

    def _lbl(self, parent, text, side="left", pad=None):
        kw = {}
        if pad:
            kw["padx"] = pad
        tk.Label(parent, text=text, font=("Segoe UI", 9),
                 bg=self.CARD, fg=self.SUB).pack(side=side, **kw)

    def _spinbox(self, parent, var, from_, to, inc, width=5):
        tk.Spinbox(parent, from_=from_, to=to, increment=inc, width=width,
                   textvariable=var, font=("Segoe UI", 9),
                   bg=self.SURFACE, fg=self.TXT, buttonbackground=self.CARD,
                   relief="flat", insertbackground=self.TXT).pack(side="right")

    def _spinbox_in(self, parent, var, from_, to, inc, width, fmt=None):
        kw = {}
        if fmt:
            kw["format"] = fmt
        tk.Spinbox(parent, from_=from_, to=to, increment=inc, width=width,
                   textvariable=var, font=("Segoe UI", 9),
                   bg=self.SURFACE, fg=self.TXT, buttonbackground=self.CARD,
                   relief="flat", insertbackground=self.TXT, **kw).pack(side="left")

    def _small_btn(self, parent, text, cmd, side="left", padx=0):
        tk.Button(parent, text=text, font=("Segoe UI", 8),
                  bg=self.SURFACE, fg=self.TXT, activebackground=self.BORDER,
                  activeforeground=self.TXT, relief="flat", cursor="hand2",
                  command=cmd, bd=0, padx=8, pady=2).pack(side=side, padx=(padx, 0))

    # ── Anti-veille logic ──────────────────────────────

    def _parse_stop_time(self):
        try:
            h = int(self.timer_hour.get())
            m = int(self.timer_min.get())
        except (ValueError, tk.TclError):
            return None
        if not (0 <= h <= 23 and 0 <= m <= 59):
            return None
        now = datetime.now()
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target

    def _toggle(self):
        self.active = not self.active
        if self.active:
            try:
                self.interval = max(5, int(self.interval_var.get()))
            except ValueError:
                self.interval = 30
            try:
                self.distance = max(1, int(self.distance_var.get()))
            except ValueError:
                self.distance = 5
            self.stop_time = self._parse_stop_time()
            self.started_at = datetime.now()
            self.moves = 0
            keep_awake(True)
            self.btn.configure(text="⏸  Couper", bg=self.RED)
            self.status_dot.configure(fg=self.GREEN)
            self.status_lbl.configure(text="ON")
        else:
            self._deactivate()

    def _deactivate(self):
        self.active = False
        self.stop_time = None
        keep_awake(False)
        self.btn.configure(text="▶  Lancer", bg=self.ACCENT)
        self.status_dot.configure(fg=self.RED)
        self.status_lbl.configure(text="OFF")
        self.footer.configure(text="En attente... zzz")
        self.timer_lbl.configure(text="")

    def _start_worker(self):
        def loop():
            while self.running:
                if self.active:
                    dx, dy = DIRECTIONS[self.step % 4]
                    move_mouse(dx * self.distance, dy * self.distance)
                    self.step += 1
                    self.moves += 1
                    for _ in range(self.interval * 10):
                        if not self.running or not self.active:
                            break
                        time.sleep(0.1)
                else:
                    time.sleep(0.25)
        threading.Thread(target=loop, daemon=True).start()

    def _tick_footer(self):
        if self.active and self.started_at:
            elapsed = int((datetime.now() - self.started_at).total_seconds())
            h, rem = divmod(elapsed, 3600)
            m, s = divmod(rem, 60)
            self.footer.configure(text=f"{h:02d}:{m:02d}:{s:02d}  ·  {self.moves} mvt")
        self.root.after(1000, self._tick_footer)

    def _tick_timer(self):
        if self.active and self.stop_time:
            remaining = (self.stop_time - datetime.now()).total_seconds()
            if remaining <= 0:
                self._deactivate()
                self.timer_lbl.configure(text="Fini !", fg=self.PINK)
            else:
                h, rem = divmod(int(remaining), 3600)
                m, s = divmod(rem, 60)
                self.timer_lbl.configure(
                    text=f"Arrêt dans {h:02d}:{m:02d}:{s:02d}", fg=self.PINK
                )
        self.root.after(1000, self._tick_timer)

    # ── Transcription ──────────────────────────────────

    def _init_transcription(self):
        if not HAS_TRANSCRIPTION:
            return
        self._overlay = None
        self._overlay_hide_id = None
        self._pulse_id = None

        lang_code = LANG_MAP.get(self.lang_var.get(), "") or None

        def on_status(msg, is_recording):
            self.root.after(0, lambda: self._handle_trans_status(msg, is_recording))

        def on_result(text):
            self.root.after(0, lambda: self._add_to_history(text))

        def on_level(peak):
            self.root.after(0, lambda: self._update_rec_level(peak))

        # Resolve saved mic device
        self._refresh_mic_list()
        mic_dev = None
        sel = self.mic_combo.current()
        if 0 <= sel < len(self._mic_devices):
            mic_dev = self._mic_devices[sel][0]

        self.transcriber = VoiceTranscriber(
            api_key=self.api_key_var.get(),
            language=lang_code,
            sound=self.sound_var.get(),
            device=mic_dev,
            on_status=on_status,
            on_result=on_result,
            on_level=on_level,
        )
        self.transcriber.start()

        # Sync settings live
        self.api_key_var.trace_add("write", self._sync_transcriber)
        self.lang_var.trace_add("write", self._sync_transcriber)
        self.sound_var.trace_add("write", self._sync_transcriber)

        # Start mic polling
        self._tick_mic_check()

    def _sync_transcriber(self, *_):
        if not self.transcriber:
            return
        self.transcriber.update_key(self.api_key_var.get())
        self.transcriber.update_language(LANG_MAP.get(self.lang_var.get(), "") or None)
        self.transcriber.sound = self.sound_var.get()

    # ── Mic management ─────────────────────────────────

    def _refresh_mic_list(self):
        """Enumere les peripheriques d'entree et peuple le dropdown."""
        try:
            devices = VoiceTranscriber.list_input_devices()
        except Exception:
            devices = []

        self._mic_devices = devices
        names = [d[1] for d in devices]
        self.mic_combo["values"] = names

        if not devices:
            self.mic_status.configure(text="Aucun micro detecte", fg=self.RED)
            self.mic_var.set("")
            return

        saved = self.config.get("mic_device_name", "")
        selected_idx = 0
        for i, (dev_idx, name) in enumerate(devices):
            if name == saved:
                selected_idx = i
                break

        self.mic_var.set(names[selected_idx])
        self.mic_combo.current(selected_idx)
        self.mic_status.configure(
            text=f"Micro: {names[selected_idx][:30]}", fg=self.GREEN
        )

    def _on_mic_selected(self, event=None):
        sel = self.mic_combo.current()
        if 0 <= sel < len(self._mic_devices):
            dev_idx, name = self._mic_devices[sel]
            if self.transcriber:
                self.transcriber.update_device(dev_idx)
            self.mic_status.configure(
                text=f"Micro: {name[:30]}", fg=self.GREEN
            )

    def _test_mic(self):
        if not HAS_TRANSCRIPTION or not self.transcriber:
            return
        if self.transcriber.recording:
            self.mic_status.configure(text="Enregistrement en cours", fg=self.RED)
            return
        if not self._mic_devices:
            self.mic_status.configure(text="Aucun micro detecte", fg=self.RED)
            return
        sel = self.mic_combo.current()
        dev = self._mic_devices[sel][0] if 0 <= sel < len(self._mic_devices) else None
        self.mic_status.configure(text="Test en cours...", fg=self.PINK)
        self.test_level.delete("all")

        def on_result(detected, peak):
            def _update():
                self.test_level.delete("all")
                bar_w = int(peak * 80)
                color = self.GREEN if detected else self.RED
                self.test_level.create_rectangle(0, 0, bar_w, 12,
                                                  fill=color, outline="")
                if detected:
                    self.mic_status.configure(text="Micro OK !", fg=self.GREEN)
                else:
                    self.mic_status.configure(text="Aucun son detecte", fg=self.RED)
            self.root.after(0, _update)

        self.transcriber.test_mic(device=dev, callback=on_result)

    def _tick_mic_check(self):
        """Verifie les changements de micro toutes les 5 secondes."""
        if HAS_TRANSCRIPTION:
            try:
                current = VoiceTranscriber.list_input_devices()
                current_names = {d[1] for d in current}
                cached_names = {d[1] for d in self._mic_devices}
                if current_names != cached_names:
                    self._refresh_mic_list()
                    if self.transcriber:
                        sel = self.mic_combo.current()
                        if 0 <= sel < len(self._mic_devices):
                            self.transcriber.update_device(
                                self._mic_devices[sel][0]
                            )
            except Exception:
                pass
        self.root.after(5000, self._tick_mic_check)

    # ── Recording level bar ────────────────────────────

    def _update_rec_level(self, peak):
        self.rec_level.delete("all")
        if not self.transcriber or not self.transcriber.recording:
            return
        w = self.rec_level.winfo_width()
        bar_w = int(peak * w)
        color = self.GREEN if peak < 0.7 else self.PINK
        self.rec_level.create_rectangle(0, 0, bar_w, 6, fill=color, outline="")

    # ── Status & overlay ───────────────────────────────

    def _handle_trans_status(self, msg, is_recording):
        if is_recording:
            color = self.RED
        elif "OK" in msg or "Pret" in msg:
            color = self.GREEN
        elif "Erreur" in msg or "manquant" in msg or "introuvable" in msg:
            color = self.RED
        else:
            color = self.PINK
        self.trans_status.configure(text=msg, fg=color)

        self._show_overlay(msg)
        if not is_recording:
            self.rec_level.delete("all")
            if self._pulse_id:
                self.root.after_cancel(self._pulse_id)
                self._pulse_id = None
            if self._overlay_hide_id:
                self.root.after_cancel(self._overlay_hide_id)
            self._overlay_hide_id = self.root.after(2000, self._hide_overlay)
        else:
            self._pulse_overlay()

    def _show_overlay(self, text):
        is_rec = "Enregistrement" in text
        is_processing = "Transcription" in text
        is_error = "Erreur" in text or "introuvable" in text

        if is_rec:
            color = self.RED
            prefix = "●  "
        elif is_processing:
            color = self.ACCENT
            prefix = ""
        elif is_error:
            color = self.RED
            prefix = ""
        else:
            color = self.SURFACE
            prefix = ""

        display = prefix + text
        if self._overlay is None:
            self._overlay = tk.Toplevel(self.root)
            self._overlay.overrideredirect(True)
            self._overlay.attributes("-topmost", True)
            try:
                self._overlay.attributes("-alpha", 0.92)
            except tk.TclError:
                pass
            self._overlay_lbl = tk.Label(
                self._overlay, font=("Segoe UI", 10, "bold"), padx=18, pady=6,
            )
            self._overlay_lbl.pack()
        self._overlay_lbl.configure(text=display, bg=color, fg="white")
        self._overlay.configure(bg=color)
        self._overlay.update_idletasks()
        ow = self._overlay.winfo_reqwidth()
        sx = (self.root.winfo_screenwidth() - ow) // 2
        self._overlay.geometry(f"+{sx}+12")
        self._overlay.deiconify()

    def _pulse_overlay(self):
        """Pulsation visuelle de l'overlay pendant l'enregistrement."""
        if self._overlay and self.transcriber and self.transcriber.recording:
            current = self._overlay_lbl.cget("bg")
            next_color = "#e06080" if current == self.RED else self.RED
            self._overlay_lbl.configure(bg=next_color)
            self._overlay.configure(bg=next_color)
            self._pulse_id = self.root.after(600, self._pulse_overlay)

    def _hide_overlay(self):
        if self._overlay:
            self._overlay.withdraw()

    # ── History ────────────────────────────────────────

    def _refresh_history(self):
        self.history_list.delete(0, tk.END)
        for item in self.history[-10:]:
            display = item[:60] + "..." if len(item) > 60 else item
            self.history_list.insert(tk.END, display)

    def _add_to_history(self, text):
        self.history.append(text)
        self.history = self.history[-10:]
        self._refresh_history()

    def _copy_history_item(self):
        sel = self.history_list.curselection()
        if sel and sel[0] < len(self.history):
            self.root.clipboard_clear()
            self.root.clipboard_append(self.history[sel[0]])

    def _clear_history(self):
        self.history.clear()
        self._refresh_history()

    # ── TTS actions ────────────────────────────────────

    def _init_tts(self):
        if not HAS_TTS:
            return

        def on_status(msg, is_speaking):
            self.root.after(0, lambda: self._handle_tts_status(msg, is_speaking))

        api_key = self.config.get("mistral_api_key", "")
        saved_voice = self.config.get("tts_voice", "fr_female")

        self.tts_reader = TextToSpeechReader(
            api_key=api_key,
            voice_id=saved_voice,
            on_status=on_status,
        )

        # Populate voice list
        voices = self.tts_reader.get_voices()
        if voices:
            self._tts_voice_ids = [v[0] for v in voices]
            names = [v[1] for v in voices]
            self.tts_voice_combo["values"] = names
            if saved_voice in self._tts_voice_ids:
                idx = self._tts_voice_ids.index(saved_voice)
                self.tts_voice_var.set(names[idx])
            else:
                self.tts_voice_var.set(names[0])
        else:
            self._tts_voice_ids = []

    def _handle_tts_status(self, msg, is_speaking):
        color = self.PINK if is_speaking else self.SUB
        self.tts_status.configure(text=msg, fg=color)
        if is_speaking:
            self.tts_play_btn.configure(text="▶  Ca parle...", bg=self.RED)
        else:
            self.tts_play_btn.configure(text="▶  Lire", bg=self.ACCENT)

    def _tts_play(self):
        if not HAS_TTS:
            return
        text = self.tts_text.get("1.0", tk.END).strip()
        if not text:
            return
        # Sync API key
        self.tts_reader.update_key(self.api_key_var.get())
        voice_id = None
        sel = self.tts_voice_combo.current()
        if sel >= 0 and sel < len(self._tts_voice_ids):
            voice_id = self._tts_voice_ids[sel]
        self.tts_reader.speak(text, voice_id)

    def _tts_stop(self):
        if HAS_TTS and hasattr(self, "tts_reader"):
            self.tts_reader.stop()

    def _tts_paste(self):
        try:
            text = self.root.clipboard_get()
            self.tts_text.delete("1.0", tk.END)
            self.tts_text.insert("1.0", text)
        except tk.TclError:
            pass

    def _tts_clear(self):
        self.tts_text.delete("1.0", tk.END)

    # ── Settings actions ───────────────────────────────

    def _toggle_autostart(self):
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_SET_VALUE,
            )
            if self.autostart_var.get():
                exe = sys.executable
                if getattr(sys, "frozen", False):
                    exe = sys.executable
                winreg.SetValueEx(key, "LetMeSleep", 0, winreg.REG_SZ, f'"{exe}"')
            else:
                try:
                    winreg.DeleteValue(key, "LetMeSleep")
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
        except Exception:
            pass

    def _toggle_topmost(self):
        self.root.attributes("-topmost", self.topmost_var.get())

    # ── System Tray ────────────────────────────────────

    def _init_tray(self):
        if not HAS_TRAY:
            return
        png = resource_path("images_transparent.png")
        if not os.path.exists(png):
            return
        try:
            img = PILImage.open(png)
            self.tray_icon = pystray.Icon(
                "letmesleep", img, "LetMeSleep",
                menu=pystray.Menu(
                    pystray.MenuItem("Afficher", self._show_from_tray, default=True),
                    pystray.MenuItem("Quitter", self._quit_from_tray),
                ),
            )
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
        except Exception:
            self.tray_icon = None

    def _show_from_tray(self, *_):
        self.root.after(0, self.root.deiconify)

    def _quit_from_tray(self, *_):
        self.root.after(0, self._quit)

    def _on_close(self):
        if self.tray_var.get() and self.tray_icon:
            self.root.withdraw()
        else:
            self._quit()

    # ── Save & Quit ────────────────────────────────────

    def _save_config(self):
        self.config["mistral_api_key"] = self.api_key_var.get()
        self.config["language"] = self.lang_var.get()
        self.config["sound_feedback"] = self.sound_var.get()
        self.config["minimize_to_tray"] = self.tray_var.get()
        self.config["autostart"] = self.autostart_var.get()
        self.config["always_on_top"] = self.topmost_var.get()
        self.config["history"] = self.history[-10:]
        sel = self.tts_voice_combo.current()
        if sel >= 0 and sel < len(self._tts_voice_ids):
            self.config["tts_voice"] = self._tts_voice_ids[sel]
        mic_sel = self.mic_combo.current()
        if 0 <= mic_sel < len(self._mic_devices):
            self.config["mic_device_name"] = self._mic_devices[mic_sel][1]
        save_config(self.config)

    def _quit(self):
        self.running = False
        self.active = False
        keep_awake(False)
        self._save_config()
        if self.transcriber:
            self.transcriber.stop()
        if self.tts_reader:
            self.tts_reader.stop()
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        self.root.destroy()


if __name__ == "__main__":
    LetMeSleep()
