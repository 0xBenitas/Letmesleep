"""
LetMeSleep — Outil anti-veille mignon et léger.
Zéro dépendance externe (tkinter + ctypes uniquement).
Conçu pour tourner en arrière-plan sur un PC pro.
"""

import ctypes
import os
import sys
import threading
import time
import tkinter as tk
from datetime import datetime, timedelta

# ── Windows API (déplacement souris sans lib externe) ───
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


# Empêche aussi la mise en veille Windows
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


def resource_path(relative_path):
    """Résout le chemin vers une ressource, compatible PyInstaller."""
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)


# ── App ─────────────────────────────────────────────────
DIRECTIONS = [(1, 0), (0, 1), (-1, 0), (0, -1)]


class LetMeSleep:
    def __init__(self):
        self.active = False
        self.running = True
        self.interval = 30
        self.distance = 5
        self.step = 0
        self.started_at = None
        self.moves = 0
        self.stop_time = None  # datetime cible d'arrêt

        self._build_ui()
        self._start_worker()
        self._tick_footer()
        self._tick_timer()
        self.root.mainloop()

    # ── UI ──────────────────────────────────────────────
    def _build_ui(self):
        self.root = tk.Tk()
        self.root.title("LetMeSleep")
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)
        self.root.protocol("WM_DELETE_WINDOW", self._quit)

        # Icône
        ico = resource_path("images_transparent.ico")
        if os.path.exists(ico):
            try:
                self.root.iconbitmap(ico)
            except tk.TclError:
                pass

        # Taille & position coin bas-droit
        w, h = 310, 370
        sx = self.root.winfo_screenwidth() - w - 20
        sy = self.root.winfo_screenheight() - h - 60
        self.root.geometry(f"{w}x{h}+{sx}+{sy}")

        # ── Palette Catppuccin Mocha ──
        BG = "#1e1e2e"
        CARD = "#282840"
        TXT = "#cdd6f4"
        SUB = "#6c7086"
        GREEN = "#a6e3a1"
        RED = "#f38ba8"
        ACCENT = "#cba6f7"  # Mauve — plus mignon
        PINK = "#f5c2e7"
        BORDER = "#45475a"

        self.BG = BG
        self.GREEN, self.RED, self.ACCENT, self.SUB = GREEN, RED, ACCENT, SUB
        self.PINK, self.TXT, self.CARD, self.BORDER = PINK, TXT, CARD, BORDER
        self.root.configure(bg=BG)

        # ─ Header avec logo
        head = tk.Frame(self.root, bg=BG)
        head.pack(fill="x", padx=16, pady=(14, 2))

        # Logo PNG
        self.logo_img = None
        png = resource_path("images_transparent.png")
        if os.path.exists(png):
            try:
                self.logo_img = tk.PhotoImage(file=png)
                # Réduire à ~32px
                orig_w = self.logo_img.width()
                factor = max(1, orig_w // 32)
                self.logo_img = self.logo_img.subsample(factor, factor)
                tk.Label(head, image=self.logo_img, bg=BG).pack(side="left", padx=(0, 8))
            except tk.TclError:
                pass

        tk.Label(
            head, text="LetMeSleep", font=("Segoe UI", 14, "bold"),
            bg=BG, fg=PINK
        ).pack(side="left")

        self.status_dot = tk.Label(
            head, text="●", font=("Segoe UI", 12), bg=BG, fg=RED
        )
        self.status_dot.pack(side="right")
        self.status_lbl = tk.Label(
            head, text="Inactif", font=("Segoe UI", 9), bg=BG, fg=SUB
        )
        self.status_lbl.pack(side="right", padx=(0, 4))

        # ─ Sous-titre
        tk.Label(
            self.root, text="Anti-veille tout doux", font=("Segoe UI", 8),
            bg=BG, fg=SUB
        ).pack(anchor="w", padx=16, pady=(0, 8))

        # ─ Card Réglages
        card = tk.Frame(self.root, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="x", padx=16, pady=(0, 6))

        tk.Label(
            card, text="Réglages", font=("Segoe UI", 9, "bold"),
            bg=CARD, fg=TXT
        ).pack(anchor="w", padx=12, pady=(8, 2))

        # Ligne intervalle
        row1 = tk.Frame(card, bg=CARD)
        row1.pack(fill="x", padx=12, pady=(4, 2))
        tk.Label(row1, text="Intervalle", font=("Segoe UI", 9), bg=CARD, fg=SUB).pack(side="left")
        self.interval_var = tk.StringVar(value="30")
        tk.Spinbox(
            row1, from_=5, to=300, increment=5, width=5,
            textvariable=self.interval_var, font=("Segoe UI", 9),
            bg="#313244", fg=TXT, buttonbackground=CARD,
            relief="flat", insertbackground=TXT
        ).pack(side="right")
        tk.Label(row1, text="sec", font=("Segoe UI", 9), bg=CARD, fg=SUB).pack(side="right", padx=(0, 4))

        # Ligne distance
        row2 = tk.Frame(card, bg=CARD)
        row2.pack(fill="x", padx=12, pady=(2, 8))
        tk.Label(row2, text="Distance", font=("Segoe UI", 9), bg=CARD, fg=SUB).pack(side="left")
        self.distance_var = tk.StringVar(value="5")
        tk.Spinbox(
            row2, from_=1, to=50, increment=1, width=5,
            textvariable=self.distance_var, font=("Segoe UI", 9),
            bg="#313244", fg=TXT, buttonbackground=CARD,
            relief="flat", insertbackground=TXT
        ).pack(side="right")
        tk.Label(row2, text="px", font=("Segoe UI", 9), bg=CARD, fg=SUB).pack(side="right", padx=(0, 4))

        # ─ Card Timer
        timer_card = tk.Frame(self.root, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        timer_card.pack(fill="x", padx=16, pady=(0, 6))

        tk.Label(
            timer_card, text="Arrêt programmé", font=("Segoe UI", 9, "bold"),
            bg=CARD, fg=TXT
        ).pack(anchor="w", padx=12, pady=(8, 2))

        row_timer = tk.Frame(timer_card, bg=CARD)
        row_timer.pack(fill="x", padx=12, pady=(4, 8))

        tk.Label(row_timer, text="Arrêter à", font=("Segoe UI", 9), bg=CARD, fg=SUB).pack(side="left")

        self.timer_hour = tk.StringVar(value="")
        self.timer_min = tk.StringVar(value="")

        time_frame = tk.Frame(row_timer, bg=CARD)
        time_frame.pack(side="right")

        tk.Spinbox(
            time_frame, from_=0, to=23, increment=1, width=3,
            textvariable=self.timer_hour, font=("Segoe UI", 9),
            bg="#313244", fg=TXT, buttonbackground=CARD,
            relief="flat", insertbackground=TXT, format="%02.0f"
        ).pack(side="left")
        tk.Label(time_frame, text="h", font=("Segoe UI", 9, "bold"), bg=CARD, fg=PINK).pack(side="left", padx=2)
        tk.Spinbox(
            time_frame, from_=0, to=59, increment=5, width=3,
            textvariable=self.timer_min, font=("Segoe UI", 9),
            bg="#313244", fg=TXT, buttonbackground=CARD,
            relief="flat", insertbackground=TXT, format="%02.0f"
        ).pack(side="left")

        # Label countdown
        self.timer_lbl = tk.Label(
            timer_card, text="", font=("Segoe UI", 8), bg=CARD, fg=SUB
        )
        self.timer_lbl.pack(pady=(0, 6))

        # ─ Bouton toggle
        self.btn = tk.Button(
            self.root, text="▶  Activer", font=("Segoe UI", 11, "bold"),
            bg=ACCENT, fg="#1e1e2e", activebackground=ACCENT,
            activeforeground="#1e1e2e", relief="flat", cursor="hand2",
            command=self._toggle, height=1, bd=0
        )
        self.btn.pack(fill="x", padx=16, pady=(4, 6))

        # ─ Footer stats
        self.footer = tk.Label(
            self.root, text="Prêt — zzz", font=("Segoe UI", 8), bg=BG, fg=SUB
        )
        self.footer.pack(pady=(0, 10))

    # ── Logic ───────────────────────────────────────────
    def _parse_stop_time(self):
        """Retourne un datetime cible ou None."""
        try:
            h = int(self.timer_hour.get())
            m = int(self.timer_min.get())
        except (ValueError, tk.TclError):
            return None

        if not (0 <= h <= 23 and 0 <= m <= 59):
            return None

        now = datetime.now()
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        # Si l'heure est déjà passée aujourd'hui, on vise demain
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
            self.btn.configure(text="⏸  Désactiver", bg=self.RED)
            self.status_dot.configure(fg=self.GREEN)
            self.status_lbl.configure(text="Actif")
        else:
            self._deactivate()

    def _deactivate(self):
        self.active = False
        self.stop_time = None
        keep_awake(False)
        self.btn.configure(text="▶  Activer", bg=self.ACCENT)
        self.status_dot.configure(fg=self.RED)
        self.status_lbl.configure(text="Inactif")
        self.footer.configure(text="Prêt — zzz")
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

        t = threading.Thread(target=loop, daemon=True)
        t.start()

    def _tick_footer(self):
        """Met à jour le compteur chaque seconde."""
        if self.active and self.started_at:
            elapsed = int((datetime.now() - self.started_at).total_seconds())
            h, rem = divmod(elapsed, 3600)
            m, s = divmod(rem, 60)
            self.footer.configure(
                text=f"{h:02d}:{m:02d}:{s:02d}  ·  {self.moves} mvt"
            )
        self.root.after(1000, self._tick_footer)

    def _tick_timer(self):
        """Vérifie le timer et affiche le countdown."""
        if self.active and self.stop_time:
            remaining = (self.stop_time - datetime.now()).total_seconds()
            if remaining <= 0:
                self._deactivate()
                self.timer_lbl.configure(text="Terminé !", fg=self.PINK)
            else:
                h, rem = divmod(int(remaining), 3600)
                m, s = divmod(rem, 60)
                self.timer_lbl.configure(
                    text=f"Arrêt dans {h:02d}:{m:02d}:{s:02d}",
                    fg=self.PINK
                )
        self.root.after(1000, self._tick_timer)

    def _quit(self):
        self.running = False
        self.active = False
        keep_awake(False)
        self.root.destroy()


if __name__ == "__main__":
    LetMeSleep()
