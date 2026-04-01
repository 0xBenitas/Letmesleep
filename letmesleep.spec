# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec pour LetMeSleep
# Usage : pyinstaller letmesleep.spec

a = Analysis(
    ['letmesleep.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('images_transparent.png', '.'),
        ('images_transparent.ico', '.'),
    ],
    hiddenimports=[
        'tts',
        'transcription',
        'mistralai',
        'sounddevice',
        'numpy',
        'pynput',
        'pystray',
        'PIL',
        '_sounddevice_data',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='LetMeSleep',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # Pas de console, juste la fenêtre
    icon='images_transparent.ico',
)
