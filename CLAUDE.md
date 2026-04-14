# CLAUDE.md

Guidance for Claude Code when working on **Hush** — an extensible toolbox for remote workers.

---

## What Hush is

Hush is a desktop app that bundles several independent "tools" behind a single clean UI. The app is designed to grow over time: new tools should be addable as self-contained modules without touching the core.

**Tools in v1:**
- **Dictate** — global hotkey → voice → transcription (Voxtral) → text pasted at cursor
- **Read Aloud** — paste text → Mistral reformulates for audio flow → ElevenLabs TTS with a nice audio player
- **Jiggler** — keeps the machine "active" (mouse micro-moves, prevents sleep/away status)
- **Macros** — record mouse+keyboard actions with a screenshot preview, replay them on demand

**Planned (future tools, not in v1):** clipboard history, window switcher, focus timer, etc. Architecture must make these trivial to add.

Hush is Windows-first. Cross-platform is not a goal in v1 but the code should not make it impossible later.

---

## Tech stack

| Layer | Choice |
|---|---|
| Shell | **Electron** |
| UI | **React 18 + TypeScript (strict)** |
| Styling | **Tailwind CSS + shadcn/ui** (components in `src/components/ui`) |
| State | **Zustand** (one store per tool, one global store for app state) |
| Data fetching | **TanStack Query** for API calls (Mistral, ElevenLabs) |
| Bundler | **Vite** (via `electron-vite`) |
| Packaging | **electron-builder** → NSIS installer for Windows |
| Icons | **lucide-react** |
| Audio waveform | **wavesurfer.js** |
| Global hotkeys | Electron `globalShortcut` + `uiohook-napi` if finer hooks are needed |
| Mouse/keyboard simulation | `robotjs` or `@nut-tree-fork/nut-js` |
| Autostart | `auto-launch` |
| Tray | Electron `Tray` API |

**External services:**
- **Mistral API** — Voxtral (transcription) + chat (reformulation for TTS)
- **ElevenLabs** — TTS

API keys are stored via Electron `safeStorage` (DPAPI on Windows). Never in plaintext, never in git.

---

## Repository layout

The full layout and the **module pattern for adding new tools** live in [`ARCHITECTURE.md`](./ARCHITECTURE.md). Read it before adding or modifying a tool.

Quick map:
```
hush/
├── electron/               Main process (Node): IPC, native APIs, tray, autostart
├── src/                    Renderer (React): UI, tools, components
│   └── tools/<tool>/       Self-contained tool modules (mirror of electron/tools/<tool>)
├── shared/                 Types and constants shared between main and renderer
├── ARCHITECTURE.md
└── CLAUDE.md               (this file)
```

---

## Dev commands

```bash
npm install                 # install deps
npm run dev                 # start Electron + Vite in dev mode (HMR)
npm run lint                # eslint
npm run typecheck           # tsc --noEmit
npm run test                # vitest (unit tests on pure logic)
npm run build               # production build
npm run package             # build + electron-builder → installer
```

Always run `typecheck` and `lint` before marking a task complete. If tests exist for the area you touched, run them.

---

## Coding conventions

### TypeScript
- `strict: true` is non-negotiable. No `any` unless there is a written justification in a comment.
- Types shared between main and renderer go in `shared/types/`.
- Prefer discriminated unions over boolean flags for state machines.

### React
- Functional components only. No class components.
- Hooks live next to the component that uses them, unless reused → then `src/hooks/`.
- Component files in PascalCase (`ToolCard.tsx`), hook files in camelCase prefixed with `use` (`useHotkey.ts`).
- No prop-drilling past 2 levels; use Zustand or context.

### Styling
- Tailwind utility classes in JSX. No separate `.css` files except `globals.css`.
- Use `cn()` helper from `src/lib/utils.ts` to merge classes conditionally.
- shadcn components live in `src/components/ui/` and are edited in place when needed.
- Dark mode is the default. Light mode must work too (use `dark:` variants consistently).

### File naming
- React components: `PascalCase.tsx`
- Hooks, utilities, stores: `camelCase.ts`
- Types: `PascalCase` exported from `types.ts` in the relevant module
- One default export per file when the file represents one thing; named exports otherwise.

### IPC
- All IPC channels are declared in `shared/ipc-channels.ts` as string constants.
- Each channel has a typed request/response in `shared/types/ipc.ts`.
- Renderer talks to main through a thin typed client in `src/lib/ipc.ts`, never via `window.electron.ipcRenderer` directly from components.

### State
- Each tool owns its Zustand store in `src/tools/<tool>/store.ts`.
- Global app state (current route, theme, settings) in `src/stores/app.ts`.
- Persist settings via a single IPC call to main (which uses `electron-store` or a JSON file).

---

## Security & privacy

- **API keys**: `safeStorage.encryptString` before writing, `safeStorage.decryptString` before use. Never log them.
- **CSP**: strict Content-Security-Policy in `index.html`. `default-src 'self'`, only allowlist the exact API hosts.
- **Node integration**: OFF in renderer. `contextIsolation: true`, `sandbox: true` where possible.
- **Preload**: a single typed `preload.ts` exposes a narrow API surface via `contextBridge`.
- **External calls**: only Mistral and ElevenLabs. Anything else is a red flag.
- **User data**: transcriptions and history stay local. No telemetry unless explicitly added with user consent.

---

## What NOT to do

- Don't port code from the old Python project. The old code is deleted on purpose. Start fresh.
- Don't add a feature that wasn't asked for. No "while I was there I also refactored X".
- Don't create abstractions for a single caller. Three duplications before you extract.
- Don't add dependencies without a clear reason. Every npm package is a liability.
- Don't touch the module pattern in `ARCHITECTURE.md` without agreeing on it first — the whole extensibility story depends on it.
- Don't disable TypeScript strict mode, eslint rules, or tests to make errors go away. Fix the cause.
- Don't commit secrets, API keys, or `.env` files. `.env.example` only.
- Don't use `any`, `@ts-ignore`, or `// eslint-disable` without a comment explaining why.

---

## When adding a new tool

Follow the step-by-step guide in [`ARCHITECTURE.md`](./ARCHITECTURE.md#adding-a-new-tool). In short:

1. Create `src/tools/<tool>/` and `electron/tools/<tool>/`.
2. Write a `manifest.ts` in the renderer tool folder (id, name, icon, route, hotkeys).
3. Register the tool in `src/tools/registry.ts` and `electron/tools/registry.ts`.
4. That's it — the tool appears in the sidebar, its IPC channels are wired, its settings persist.

No changes to `App.tsx`, no changes to the sidebar, no changes to the router. If you find yourself editing those for a new tool, the pattern is broken.

---

## Commit style

- Short imperative subject, lowercase, no period: `add dictate tool skeleton`
- Scope prefix when useful: `dictate: wire voxtral transcription`
- Body explains *why*, not *what*. Reserve it for non-trivial changes.
- One logical change per commit. No "wip" or "misc fixes".

---

## When in doubt

- Re-read [`ARCHITECTURE.md`](./ARCHITECTURE.md).
- Favor small, reviewable diffs over big rewrites.
- Ask the user before making an architectural decision that isn't covered here.
