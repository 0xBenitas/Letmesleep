# ARCHITECTURE.md

How Hush is structured and how to extend it.

The #1 goal of this document: make it **obvious how to add a new tool** without touching the core.

---

## 1. High-level picture

Hush is an Electron app with two processes:

```
┌──────────────────────────────────────────────────────────────┐
│                       ELECTRON APP                           │
│                                                              │
│  ┌─────────────────────┐         ┌────────────────────────┐  │
│  │   Main process      │  IPC    │   Renderer process     │  │
│  │   (Node.js)         │ ──────► │   (React + Vite)       │  │
│  │                     │ ◄────── │                        │  │
│  │  - Native APIs      │         │  - UI (shadcn)         │  │
│  │  - Global hotkeys   │         │  - Tool modules        │  │
│  │  - Tray, autostart  │         │  - Settings screens    │  │
│  │  - Config storage   │         │                        │  │
│  │  - External APIs    │         │                        │  │
│  │    (Mistral, 11Labs)│         │                        │  │
│  └─────────────────────┘         └────────────────────────┘  │
│            │                                                 │
│            ▼                                                 │
│  Windows APIs (SendInput, SetThreadExecutionState, hooks)    │
└──────────────────────────────────────────────────────────────┘
```

**Rules of thumb:**
- Anything that touches the OS, the filesystem, external APIs, or global state → **main**.
- Anything visual or user-interactive → **renderer**.
- The renderer never imports Node modules. It goes through IPC.

---

## 2. Directory layout

```
hush/
├── electron/                           # MAIN PROCESS
│   ├── main.ts                         # app entrypoint, window + tray setup
│   ├── preload.ts                      # contextBridge — exposes typed IPC to renderer
│   ├── core/                           # shared infra, used by tools
│   │   ├── hotkeys.ts                  # global hotkey registry
│   │   ├── audio.ts                    # mic capture, audio playback
│   │   ├── input.ts                    # mouse/keyboard simulation + event hooks
│   │   ├── screen.ts                   # screenshots, active window info
│   │   ├── config.ts                   # persistent settings (electron-store)
│   │   ├── secrets.ts                  # safeStorage wrapper for API keys
│   │   └── services/                   # external API clients
│   │       ├── mistral.ts              # Voxtral + chat completion
│   │       └── elevenlabs.ts           # TTS
│   ├── tools/                          # ONE FOLDER PER TOOL
│   │   ├── registry.ts                 # auto-wires every tool's handlers
│   │   ├── dictate/
│   │   │   ├── index.ts                # register() function — IPC handlers + lifecycle
│   │   │   └── ...
│   │   ├── read-aloud/
│   │   ├── jiggler/
│   │   └── macros/
│   └── ipc-handler.ts                  # boots core + tool registry
│
├── src/                                # RENDERER (React)
│   ├── main.tsx                        # React entrypoint
│   ├── App.tsx                         # layout: sidebar + <Outlet />
│   ├── router.tsx                      # react-router config, reads tool manifests
│   ├── tools/                          # ONE FOLDER PER TOOL (mirrors electron/tools)
│   │   ├── registry.ts                 # imports all tool manifests
│   │   ├── dictate/
│   │   │   ├── manifest.ts             # { id, name, icon, route, hotkeys }
│   │   │   ├── DictatePage.tsx         # main view
│   │   │   ├── store.ts                # Zustand store (tool-local state)
│   │   │   ├── ipc.ts                  # typed client for this tool's IPC channels
│   │   │   └── components/             # tool-specific components
│   │   ├── read-aloud/
│   │   ├── jiggler/
│   │   └── macros/
│   ├── components/
│   │   ├── ui/                         # shadcn/ui primitives (Button, Input, etc.)
│   │   └── layout/                     # Sidebar, Header, etc.
│   ├── stores/
│   │   └── app.ts                      # global app state (theme, route, etc.)
│   ├── hooks/
│   ├── lib/
│   │   ├── utils.ts                    # cn() etc.
│   │   └── ipc.ts                      # base typed IPC client
│   └── styles/
│       └── globals.css
│
├── shared/                             # SHARED (imported by both sides)
│   ├── ipc-channels.ts                 # string constants for every IPC channel
│   └── types/
│       ├── ipc.ts                      # request/response types per channel
│       ├── tool.ts                     # ToolManifest, ToolId
│       └── settings.ts                 # AppSettings, per-tool settings
│
├── resources/                          # icons, sounds, static assets
├── CLAUDE.md
├── ARCHITECTURE.md                     # this file
├── package.json
├── tsconfig.json
├── tailwind.config.ts
├── electron-builder.yml
└── vite.config.ts
```

---

## 3. The tool module pattern

A **tool** is a self-contained feature. It lives in two mirrored folders:

- `electron/tools/<tool>/` — the main-process side (IPC handlers, native code, API calls)
- `src/tools/<tool>/` — the renderer side (UI, state, typed IPC client)

Both sides communicate via IPC channels declared in `shared/ipc-channels.ts`.

### 3.1 The manifest (renderer side)

Every tool exports a `ToolManifest`:

```ts
// src/tools/dictate/manifest.ts
import { Mic } from "lucide-react";
import type { ToolManifest } from "@shared/types/tool";
import { DictatePage } from "./DictatePage";

export const dictateManifest: ToolManifest = {
  id: "dictate",
  name: "Dictate",
  description: "Voice to text, anywhere.",
  icon: Mic,
  route: "/dictate",
  component: DictatePage,
  defaultHotkeys: {
    toggle: "CommandOrControl+Alt+R",
  },
};
```

The manifest is the **only thing the app shell needs to know** about the tool. The sidebar, the router, and the hotkey registry all read from it.

### 3.2 The tool registry (renderer)

```ts
// src/tools/registry.ts
import { dictateManifest } from "./dictate/manifest";
import { readAloudManifest } from "./read-aloud/manifest";
import { jigglerManifest } from "./jiggler/manifest";
import { macrosManifest } from "./macros/manifest";

export const tools = [
  dictateManifest,
  readAloudManifest,
  jigglerManifest,
  macrosManifest,
] as const;
```

Everywhere the app iterates over tools (sidebar, router, settings) it reads this array. **Nothing else knows the list.**

### 3.3 The main-side registration

Each tool in `electron/tools/<tool>/index.ts` exports a `register()`:

```ts
// electron/tools/dictate/index.ts
import { ipcMain } from "electron";
import { IPC } from "@shared/ipc-channels";
import { transcribe } from "./transcribe";

export function register() {
  ipcMain.handle(IPC.DICTATE_START, async (_e, payload) => {
    return transcribe(payload);
  });
  // ... other handlers, hotkey bindings, lifecycle hooks
}

export function dispose() {
  // cleanup: unregister hotkeys, stop timers, etc.
}
```

And the main registry:

```ts
// electron/tools/registry.ts
import * as dictate from "./dictate";
import * as readAloud from "./read-aloud";
import * as jiggler from "./jiggler";
import * as macros from "./macros";

const toolModules = [dictate, readAloud, jiggler, macros];

export function registerAllTools() {
  toolModules.forEach((m) => m.register());
}

export function disposeAllTools() {
  toolModules.forEach((m) => m.dispose?.());
}
```

### 3.4 IPC contract per tool

- Channel names live in `shared/ipc-channels.ts`, namespaced by tool:
  ```ts
  export const IPC = {
    DICTATE_START: "dictate:start",
    DICTATE_STOP: "dictate:stop",
    READ_ALOUD_SYNTHESIZE: "read-aloud:synthesize",
    JIGGLER_SET_STATE: "jiggler:set-state",
    MACROS_RECORD: "macros:record",
    // ...
  } as const;
  ```
- Types live in `shared/types/ipc.ts`:
  ```ts
  export interface DictateStartPayload { language?: string; }
  export interface DictateStartResult { text: string; durationMs: number; }
  ```
- The renderer calls them via a typed client in the tool's `ipc.ts`:
  ```ts
  // src/tools/dictate/ipc.ts
  import { invoke } from "@/lib/ipc";
  import { IPC } from "@shared/ipc-channels";
  import type { DictateStartPayload, DictateStartResult } from "@shared/types/ipc";

  export const dictateIpc = {
    start: (p: DictateStartPayload) =>
      invoke<DictateStartResult>(IPC.DICTATE_START, p),
  };
  ```

This gives you **fully typed IPC across processes**, with no stringly-typed calls in components.

---

## 4. Adding a new tool

Say you want to add a **Clipboard History** tool.

### Step 1 — Create the folders
```
electron/tools/clipboard-history/
  index.ts

src/tools/clipboard-history/
  manifest.ts
  ClipboardHistoryPage.tsx
  store.ts
  ipc.ts
```

### Step 2 — Declare IPC channels and types
Add to `shared/ipc-channels.ts`:
```ts
CLIPBOARD_HISTORY_LIST: "clipboard-history:list",
CLIPBOARD_HISTORY_CLEAR: "clipboard-history:clear",
```
Add request/response types to `shared/types/ipc.ts`.

### Step 3 — Implement the main side
```ts
// electron/tools/clipboard-history/index.ts
import { ipcMain, clipboard } from "electron";
import { IPC } from "@shared/ipc-channels";

let history: string[] = [];
let interval: NodeJS.Timeout | null = null;

export function register() {
  interval = setInterval(() => {
    const text = clipboard.readText();
    if (text && history[0] !== text) history.unshift(text);
    if (history.length > 100) history.pop();
  }, 500);

  ipcMain.handle(IPC.CLIPBOARD_HISTORY_LIST, () => history);
  ipcMain.handle(IPC.CLIPBOARD_HISTORY_CLEAR, () => { history = []; });
}

export function dispose() {
  if (interval) clearInterval(interval);
}
```

### Step 4 — Implement the renderer side
Manifest, page component, Zustand store, typed IPC client. Pure React, nothing special.

### Step 5 — Register the tool in the two registries
```ts
// src/tools/registry.ts
import { clipboardHistoryManifest } from "./clipboard-history/manifest";
export const tools = [ ..., clipboardHistoryManifest ] as const;

// electron/tools/registry.ts
import * as clipboardHistory from "./clipboard-history";
const toolModules = [ ..., clipboardHistory ];
```

### Done.
The tool is now in the sidebar, routed, its hotkeys registered, its settings persisted, its IPC channels wired. No other file was modified.

**If you find yourself modifying `App.tsx`, `Sidebar.tsx`, or the router to add a tool, something is wrong.** Fix the core abstraction first, not the symptom.

---

## 5. Core services (main process)

These are reusable building blocks that tools consume. Think of them as the "stdlib" of Hush.

### `core/hotkeys.ts`
Wraps `globalShortcut` with a registry indexed by tool id. Tools register/unregister via:
```ts
hotkeys.bind("dictate", "toggle", "Ctrl+Alt+R", () => { ... });
hotkeys.unbindAll("dictate");
```
User-overridable from the settings UI.

### `core/audio.ts`
- `startRecording(): RecordingHandle` — mic capture to WAV buffer.
- `playAudio(buffer: Buffer, opts)` — plays audio, supports seeking and speed.
- Abstracted so we can swap the backend if needed.

### `core/input.ts`
- `typeText(text: string)` — uses `robotjs` or equivalent to emit keystrokes at cursor.
- `moveMouse(dx, dy)` — relative move.
- `startInputHook(cb)` / `stopInputHook()` — low-level hooks for Macros.

### `core/screen.ts`
- `screenshot(region?)` — PNG buffer.
- `activeWindow()` — title, PID (useful for "don't jiggle while meeting").

### `core/config.ts`
Wraps `electron-store`. Schema-validated with Zod. Exposes `get`, `set`, `subscribe`.

### `core/secrets.ts`
Wraps `safeStorage`. All API keys go through here.

### `core/services/`
Thin clients for external APIs. One file per provider. No business logic — that stays in the tool.

---

## 6. Renderer building blocks

### `components/layout/Sidebar.tsx`
Reads `tools` from the registry and renders a nav item per manifest. Active state bound to the current route.

### `components/layout/AppShell.tsx`
Holds the sidebar + `<Outlet />`. Handles theme, keyboard shortcuts at app level.

### `router.tsx`
Builds routes from `tools`:
```ts
const routes = tools.map((t) => ({ path: t.route, element: <t.component /> }));
```

### `stores/app.ts`
Theme, current route, connection status for external APIs, onboarding state.

### Tool pages
Each tool's page is a plain React component. Uses its own store and typed IPC client. Nothing global.

---

## 7. State & persistence

- **Ephemeral state** → Zustand (tool store or app store).
- **Persistent settings** → `electron-store` via `core/config.ts`, single source of truth.
- **Secrets** → `core/secrets.ts` (safeStorage).
- **History / user data** → JSON files under `app.getPath("userData")/history/<tool>.json`. Tool-scoped.

The renderer never writes to disk directly. It asks main via IPC.

---

## 8. Styling system

- Tailwind with the shadcn/ui preset.
- Design tokens in `tailwind.config.ts` (colors, radius, spacing scale).
- One accent color. Neutral grays for everything else. No rainbow.
- Dark mode by default, light mode fully supported.
- Fonts: **Inter** for UI, **JetBrains Mono** for hotkeys and code-ish surfaces.
- Icons: **lucide-react** only. No mixing icon libraries.
- Micro-animations via `framer-motion`, used sparingly.

---

## 9. Testing strategy

- **Unit tests** (Vitest) on pure logic: transcript cleanup, audio buffer math, macro timing, config validation.
- **No UI snapshot tests.** Test behavior with React Testing Library when needed, but don't over-test glue code.
- **Main process** logic tested in isolation (mock `electron` module).
- Target: every non-trivial function in `core/` and each tool's business logic has at least one test.
- Integration / e2e is out of scope for v1.

---

## 10. Build & packaging

- Dev: `npm run dev` → `electron-vite` runs Vite + Electron with HMR.
- Prod build: `npm run build` → bundles main, preload, renderer.
- Package: `npm run package` → `electron-builder` produces an NSIS installer for Windows.
- Code signing and auto-update are future concerns, not v1.

---

## 11. Non-goals for v1

- Cross-platform (macOS / Linux). Don't write Windows-specific code in a way that *couldn't* be abstracted, but don't build the abstractions yet.
- Plugin system (third-party tools). The module pattern already gives us extensibility for first-party tools; a real plugin API is a separate design.
- Cloud sync of settings or history.
- Telemetry.

---

## 12. Decision log

When a non-obvious decision is made, append a short entry here.

- **Electron over Tauri** — chosen for iteration speed and the fact that all tools' native needs (hotkeys, input simulation, screenshots, audio) have mature Node packages. Tradeoff accepted: bundle size ~100 MB.
- **Zustand over Redux** — smaller API, no boilerplate, per-tool stores fit the module pattern.
- **Mistral + ElevenLabs only** — one provider for transcription and reformulation (Mistral), best-in-class for TTS (ElevenLabs). Swap-in for local models (Whisper, Kokoro) is a future concern, kept out of v1 scope.
- **Dark mode default** — product positioning as a "pro" tool for remote workers; light mode still fully supported.
