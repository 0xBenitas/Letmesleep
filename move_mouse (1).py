"""
Move Mouse Lite — Outil léger anti-veille.
Zéro dépendance externe (tkinter + ctypes uniquement).
Conçu pour tourner en arrière-plan sur un PC pro.
"""

import ctypes
import threading
import time
import tkinter as tk
from datetime import datetime

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


# ── App ─────────────────────────────────────────────────
DIRECTIONS = [(1, 0), (0, 1), (-1, 0), (0, -1)]


class MoveMouse:
    def __init__(self):
        self.active = False
        self.running = True
        self.interval = 30
        self.distance = 5
        self.step = 0
        self.started_at = None
        self.moves = 0

        self._build_ui()
        self._start_worker()
        self._tick_footer()
        self.root.mainloop()

    # ── UI ──────────────────────────────────────────────
    def _build_ui(self):
        self.root = tk.Tk()
        self.root.title("Move Mouse")
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)
        self.root.protocol("WM_DELETE_WINDOW", self._quit)

        # Taille compacte, position coin bas-droit
        w, h = 264, 196
        sx = self.root.winfo_screenwidth() - w - 20
        sy = self.root.winfo_screenheight() - h - 60
        self.root.geometry(f"{w}x{h}+{sx}+{sy}")

        BG = "#1e1e2e"
        CARD = "#282840"
        TXT = "#cdd6f4"
        SUB = "#6c7086"
        GREEN = "#a6e3a1"
        RED = "#f38ba8"
        ACCENT = "#89b4fa"

        self.GREEN, self.RED, self.ACCENT, self.SUB = GREEN, RED, ACCENT, SUB
        self.root.configure(bg=BG)

        # ─ Header
        head = tk.Frame(self.root, bg=BG)
        head.pack(fill="x", padx=12, pady=(10, 4))

        tk.Label(
            head, text="🖱  Move Mouse", font=("Segoe UI", 11, "bold"),
            bg=BG, fg=TXT
        ).pack(side="left")

        self.status_dot = tk.Label(
            head, text="●", font=("Segoe UI", 10), bg=BG, fg=RED
        )
        self.status_dot.pack(side="right")
        self.status_lbl = tk.Label(
            head, text="Inactif", font=("Segoe UI", 9), bg=BG, fg=SUB
        )
        self.status_lbl.pack(side="right", padx=(0, 4))

        # ─ Card centrale
        card = tk.Frame(
            self.root, bg=CARD,
            highlightbackground="#313244", highlightthickness=1
        )
        card.pack(fill="x", padx=12, pady=6)

        # Ligne intervalle
        row1 = tk.Frame(card, bg=CARD)
        row1.pack(fill="x", padx=10, pady=(8, 2))
        tk.Label(
            row1, text="Intervalle", font=("Segoe UI", 9), bg=CARD, fg=SUB
        ).pack(side="left")
        self.interval_var = tk.StringVar(value="30")
        tk.Spinbox(
            row1, from_=5, to=300, increment=5, width=5,
            textvariable=self.interval_var, font=("Segoe UI", 9),
            bg="#313244", fg=TXT, buttonbackground=CARD,
            relief="flat", insertbackground=TXT
        ).pack(side="right")
        tk.Label(
            row1, text="sec", font=("Segoe UI", 9), bg=CARD, fg=SUB
        ).pack(side="right", padx=(0, 4))

        # Ligne distance
        row2 = tk.Frame(card, bg=CARD)
        row2.pack(fill="x", padx=10, pady=(2, 8))
        tk.Label(
            row2, text="Distance", font=("Segoe UI", 9), bg=CARD, fg=SUB
        ).pack(side="left")
        self.distance_var = tk.StringVar(value="5")
        tk.Spinbox(
            row2, from_=1, to=50, increment=1, width=5,
            textvariable=self.distance_var, font=("Segoe UI", 9),
            bg="#313244", fg=TXT, buttonbackground=CARD,
            relief="flat", insertbackground=TXT
        ).pack(side="right")
        tk.Label(
            row2, text="px", font=("Segoe UI", 9), bg=CARD, fg=SUB
        ).pack(side="right", padx=(0, 4))

        # ─ Bouton toggle
        self.btn = tk.Button(
            self.root, text="▶  Activer", font=("Segoe UI", 10, "bold"),
            bg=ACCENT, fg="#1e1e2e", activebackground=ACCENT,
            activeforeground="#1e1e2e", relief="flat", cursor="hand2",
            command=self._toggle, height=1
        )
        self.btn.pack(fill="x", padx=12, pady=(4, 4))

        # ─ Footer stats
        self.footer = tk.Label(
            self.root, text="Prêt", font=("Segoe UI", 8), bg=BG, fg=SUB
        )
        self.footer.pack(pady=(0, 6))

    # ── Logic ───────────────────────────────────────────
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
            self.started_at = datetime.now()
            self.moves = 0
            keep_awake(True)
            self.btn.configure(text="⏸  Désactiver", bg=self.RED)
            self.status_dot.configure(fg=self.GREEN)
            self.status_lbl.configure(text="Actif")
        else:
            keep_awake(False)
            self.btn.configure(text="▶  Activer", bg=self.ACCENT)
            self.status_dot.configure(fg=self.RED)
            self.status_lbl.configure(text="Inactif")
            self.footer.configure(text="Prêt")

    def _start_worker(self):
        def loop():
            while self.running:
                if self.active:
                    dx, dy = DIRECTIONS[self.step % 4]
                    move_mouse(dx * self.distance, dy * self.distance)
                    self.step += 1
                    self.moves += 1
                    # sleep fractionné pour réagir vite au toggle off
                    for _ in range(self.interval * 10):
                        if not self.running or not self.active:
                            break
                        time.sleep(0.1)
                else:
                    time.sleep(0.25)

        t = threading.Thread(target=loop, daemon=True)
        t.start()

    def _tick_footer(self):
        """Met à jour le compteur chaque seconde via la boucle tkinter."""
        if self.active and self.started_at:
            elapsed = int((datetime.now() - self.started_at).total_seconds())
            h, rem = divmod(elapsed, 3600)
            m, s = divmod(rem, 60)
            self.footer.configure(
                text=f"⏱ {h:02d}:{m:02d}:{s:02d}  ·  {self.moves} mvt"
            )
        self.root.after(1000, self._tick_footer)

    def _quit(self):
        self.running = False
        self.active = False
        keep_awake(False)
        self.root.destroy()


if __name__ == "__main__":
    MoveMouse()
