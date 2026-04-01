# LetMeSleep 😴

**Your corporate laptop thinks you went for coffee. You didn't. You're just vibing.**

LetMeSleep is the ultimate remote worker's sidekick — a tiny Windows app that keeps your session alive by pretending you're busy, *plus* a built-in voice-to-text tool that lets you dictate anywhere on your screen like it's 2035.

Built for people who just want their Teams status to stay green while they go make a sandwich. No judgment here.

---

## Features

### 🖱️ Anti-Sleep
- Simulates micro mouse movements at a configurable interval
- Prevents screen lock, sleep, and that dreaded "Away" status
- Scheduled auto-stop — set a time, it shuts off, no one suspects a thing

### 🎙️ Voice Transcription (Voxtral)
- Press **Ctrl+Alt+R** anywhere → speak → press again → text appears at your cursor
- Powered by [Mistral's Voxtral API](https://docs.mistral.ai/capabilities/audio/speech_to_text/) — fast, accurate, multilingual
- **13 languages** supported (French, English, Spanish, German, Chinese, Japanese, Korean, Arabic, Hindi, Portuguese, Italian, Russian, Dutch)
- Floating overlay so you know when you're recording
- Transcription history — copy any previous result with one click

### ⚙️ Settings
- **Start with Windows** — checkbox, done
- **Minimize to system tray** — out of sight, out of mind
- **Sound feedback** — beeps when recording starts/stops so you don't talk to yourself for nothing
- **Always on top** toggle
- All preferences saved automatically

  <img width="370" height="501" alt="image" src="https://github.com/user-attachments/assets/73c3b7f6-a66f-4f47-b3a2-0ad111ed9559" />


---

## Quick Start

### Option A: Download the exe (easiest)
1. Grab `LetMeSleep.exe` from [Releases](../../releases)
2. Run it
3. That's it. There is no step 3.

### Option B: Run from source
```bash
git clone https://github.com/0xBenitas/Letmesleep.git
cd Letmesleep
pip install -r requirements.txt
python letmesleep.py
```

### Option C: Build your own exe
```bash
git clone https://github.com/0xBenitas/Letmesleep.git
cd Letmesleep
build.bat
# → dist/LetMeSleep.exe
```

---

## Voice Transcription Setup

1. Get a Mistral API key at [console.mistral.ai](https://console.mistral.ai/)
2. Paste it in the **Transcription** tab
3. Pick your language (or leave on Auto)
4. **Ctrl+Alt+R** to start recording, **Ctrl+Alt+R** again to stop & transcribe

The transcribed text gets pasted wherever your cursor is — Slack, Word, Notepad, your resignation letter, whatever.

---

## UI

The app has 3 tabs:

| Tab | What it does |
|-----|-------------|
| **Anti-Veille** | Mouse jiggler settings, timer, on/off toggle |
| **Transcription** | API key, language picker, hotkey, history |
| **Réglages** | Autostart, tray, sound, always-on-top, about |

> *The UI uses the Catppuccin Mocha theme because we have taste.*

---

## Dependencies

| Package | Why |
|---------|-----|
| `mistralai` | Voxtral transcription API |
| `sounddevice` | Microphone recording |
| `numpy` | Audio buffer handling |
| `pynput` | Global hotkey + keyboard simulation |
| `pystray` | System tray icon *(optional)* |
| `Pillow` | Tray icon image *(optional)* |

Core anti-sleep works with **zero external deps** (just tkinter + ctypes). Transcription and tray features degrade gracefully if their deps are missing.

---

## FAQ

**Q: Is this cheating?**
A: It's *optimizing your availability posture*. Totally different.

**Q: Will my IT department detect this?**
A: LetMeSleep only moves the mouse a few pixels and uses standard Windows APIs. It doesn't install drivers, services, or touch anything suspicious. But hey, we're developers, not lawyers.

**Q: Can I use the voice transcription without the anti-sleep?**
A: Yes. The features are independent. Use one, both, or neither (weird flex but ok).

**Q: Why "LetMeSleep"?**
A: Because your computer won't let you. Now it will.

---

## Tech Stack

- **Python 3** — tkinter GUI, ctypes for Windows API
- **Mistral Voxtral** — speech-to-text
- **PyInstaller** — standalone .exe build
- **Catppuccin Mocha** — because dark mode is a lifestyle

---

## License

Do whatever you want with it. If your boss asks, you didn't get it from us.
