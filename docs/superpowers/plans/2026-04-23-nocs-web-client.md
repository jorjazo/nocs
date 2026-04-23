# NOCS Web Client Implementation Plan (Plan H)

> **See also:** [NOCS v0.1 plan decomposition (A–I)](./2026-04-22-v0.1-plan-decomposition.md) — full roadmap and dependencies.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the v0.1 NOCS web client — a React + Vite + TypeScript single-page app that drives every backend API surface (devices, targets, sequences, images, safety, observatories, plate solving, sessions, config) over REST + SSE, served by the existing Spring Boot app from the same origin and bundled inside the jlink release archive.

**Architecture:** A standalone `web/` Vite project at the repo root, built by Gradle through the `com.github.node-gradle.node` plugin and copied into `src/main/resources/static/` (which Spring already serves). Token-bearer auth, EventSource for SSE, TanStack Query for server cache + invalidation, React Router v6 for routing, Vitest + Testing Library for tests, plain CSS modules (no Tailwind / UI lib). All bytes live in the jar — no separate `web/` runtime directory in the archive — keeping the launcher unchanged from Plan A. A small `WebSpaController` forwards unknown non-`/api/*` GETs to `index.html` so client-side routes deep-link.

**Tech Stack:**
- React 19 + TypeScript 5.7
- Vite 7 (build, dev server, HMR)
- React Router v6 for routing
- TanStack Query 5 (`@tanstack/react-query`) for server cache + invalidation on SSE events
- Native `EventSource` for `/api/events` SSE
- Vitest 2 + `@testing-library/react` + `jsdom` for tests
- ESLint 9 (`@typescript-eslint`, `eslint-plugin-react`, `eslint-plugin-react-hooks`) + Prettier 3
- Gradle integration via `com.github.node-gradle.node` 7.1.0
- Backend additions: `WebSpaController` (Spring MVC) + a static-resources allowlist for `/assets/**` in `SecurityConfig`

## Scope

### In scope for Plan H

1. `web/` Vite + React + TypeScript scaffold with strict tsconfig, Vitest, ESLint, Prettier.
2. Gradle integration that runs `npm ci && npm run build`, copies `web/dist` into `build/generated-resources/static/`, and registers it as a `main` source-set resource so it ends up in the boot jar (and therefore the jlink archive).
3. Vite dev server with proxy for `/api` and `/api/events` to `http://localhost:8080`, so the dev loop is `npm run dev` next to `./gradlew bootRun`.
4. SPA fallback: `WebSpaController` forwards all GETs that don't match `/api/**` and have no file extension to `forward:/index.html`, so `/sequences/42` deep-links work.
5. Bearer-token bootstrap: a `LoginPanel` that captures the token, persists it in `localStorage`, and gates the rest of the app. Token rotation = clear + re-enter.
6. Typed REST client (`apiFetch`) that injects `Authorization: Bearer <token>` and unwraps JSON / 4xx / 5xx into a discriminated `ApiResult`.
7. SSE event stream provider with auto-reconnect, topic filtering, and a `useTopic(topic, type?)` subscription hook. Connection-status pill in the nav.
8. v0.1 views from spec §15:
   - **Dashboard** — device list, connect/disconnect, live state pills.
   - **Targets** — search, details, slew/sync from a chosen mount, push as active target to safety.
   - **Mount + plate solve** — manual slew/sync/park, recent-image plate-solve trigger, ASTAP install status + start.
   - **Camera / filter wheel / focuser / autofocus** controls.
   - **Sequences** — editor + runner with live progress (status/step/sub progress, pause/resume/abort).
   - **Gallery** — thumbnails grid, filters, FITS download (auth-aware blob fetch), delete.
   - **Sessions** — list + detail (events table).
   - **Safety** — rules table, latched state, e-stop with confirm, reset, post-test sensor reading, set active target.
   - **Settings** — `/api/config` key/value editor + observatories CRUD/activate.
9. Vitest unit + component tests for each view's happy path and one error path. Spring `MockMvc` integration test that hits `/` and asserts the index page references a hashed asset under `/assets/`.
10. ESLint + Prettier wired to `./gradlew check` so lint/format failures fail the build.
11. README updates documenting the dev loop and the build wiring.

### Explicitly out of scope for Plan H

- Server-side rendering, SSR auth, or session cookies.
- Component library / Tailwind / design system. Hand-rolled CSS only.
- WebSockets / gRPC; SSE is the only push channel.
- Multi-language i18n.
- Service worker / offline support.
- Deep accessibility audit (basic semantic HTML + labels only).
- Sky-chart rendering, FITS preview, or any client-side image processing (server emits stretched JPEG thumbnails per spec §15).
- Mobile-app polish — desktop-first, with a single responsive breakpoint at 800 px so a phone is usable.
- Rotating/refreshing tokens automatically — token is static (see spec §7.1).

## File Structure

All paths are relative to the repo root (`/home/jorjazo/dev/nocs/nocs`).

**New top-level directory:**

```
web/
├── package.json
├── package-lock.json            # generated by npm install
├── tsconfig.json
├── tsconfig.node.json
├── vite.config.ts
├── vitest.config.ts
├── eslint.config.mjs
├── .prettierrc.json
├── .prettierignore
├── .eslintignore
├── .gitignore                   # ignores node_modules, dist
├── index.html
├── public/
│   └── favicon.svg
└── src/
    ├── main.tsx
    ├── App.tsx
    ├── routes.tsx
    ├── styles/
    │   ├── tokens.css
    │   └── global.css
    ├── api/
    │   ├── client.ts              # apiFetch wrapper
    │   ├── token.ts               # localStorage helpers
    │   ├── types.ts               # mirrored backend DTOs
    │   └── endpoints/
    │       ├── config.ts
    │       ├── devices.ts
    │       ├── targets.ts
    │       ├── sequences.ts
    │       ├── images.ts
    │       ├── safety.ts
    │       ├── observatories.ts
    │       ├── platesolving.ts
    │       └── sessions.ts
    ├── auth/
    │   ├── AuthContext.tsx
    │   ├── AuthProvider.tsx
    │   ├── TokenGate.tsx
    │   └── LoginPanel.tsx
    ├── events/
    │   ├── EventStream.tsx
    │   ├── useTopic.ts
    │   └── connection.ts          # connection-state enum + helper
    ├── ui/
    │   ├── Layout.tsx
    │   ├── NavBar.tsx
    │   ├── ConnectionPill.tsx
    │   ├── ErrorBoundary.tsx
    │   ├── Banner.tsx
    │   ├── Card.tsx
    │   ├── DeviceStatePill.tsx
    │   ├── ConfirmButton.tsx
    │   └── ProgressBar.tsx
    ├── views/
    │   ├── DashboardView.tsx
    │   ├── SettingsView.tsx
    │   ├── TargetsView.tsx
    │   ├── MountView.tsx
    │   ├── PlateSolveView.tsx
    │   ├── CameraView.tsx
    │   ├── FilterWheelView.tsx
    │   ├── FocuserView.tsx
    │   ├── SequenceEditorView.tsx
    │   ├── SequenceRunnerView.tsx
    │   ├── GalleryView.tsx
    │   ├── SessionsView.tsx
    │   └── SafetyView.tsx
    └── test/
        ├── setup.ts
        ├── render.tsx              # renderWithProviders helper
        └── mocks.ts                # makeFetch + sse stub
```

**Backend additions** (`src/main/java/dev/nocs/web/`):

- `WebSpaController.java` — handles SPA fallback (`forward:/index.html`).
- `WebSpaConfig.java` — `WebMvcConfigurer` that maps `/assets/**` to `classpath:/static/assets/`.
- `web/api/dto/IndexHashTest` — none, but tests live in `src/test/java/dev/nocs/web/`.

**Test tree** (`src/test/java/dev/nocs/web/`):

- `WebSpaControllerTest.java` — `MockMvc` integration: GET `/`, GET `/sequences/42`, GET `/api/config`.

**Build / CI:**

- `build.gradle.kts` — add the `node-gradle` plugin, declare `npmCi` + `npmBuildWeb` tasks, wire `processResources` to depend on the npm build, copy `web/dist` into `build/generated-resources/static/`, and add lint / test tasks to `check`.
- `settings.gradle.kts` — add the node-gradle plugin to `pluginManagement`.
- `.github/workflows/ci.yml` — install Node 22, cache `web/node_modules` and `~/.npm`, run `./gradlew check runtimeDist` (the new web build runs transitively).
- `.gitignore` — add `web/dist/`, `web/node_modules/`, `build/generated-resources/`.

**Docs:**

- `README.md` — add a "Web client" section with dev loop instructions and build wiring overview.

---

## Tasks

Each task is self-contained: files listed, TDD steps with complete code, exact commands with expected output, and a commit at the end. Use the same conventions as Plan A through G (Conventional Commits, run from the repo root, JDK 25 toolchain auto-provisioned by Gradle).

> **Implementation note:** All `npm` invocations use the `node` plugin's `nodeProjectDir = file("web")` so they execute inside `web/`. When running ad hoc, `cd web && npm <cmd>` is equivalent.

---

### Task 1: Scaffold the Vite + React + TypeScript project and wire it into Gradle

**Files:**
- Create: `web/package.json`
- Create: `web/tsconfig.json`
- Create: `web/tsconfig.node.json`
- Create: `web/vite.config.ts`
- Create: `web/vitest.config.ts`
- Create: `web/index.html`
- Create: `web/public/favicon.svg`
- Create: `web/src/main.tsx`
- Create: `web/src/App.tsx`
- Create: `web/src/styles/tokens.css`
- Create: `web/src/styles/global.css`
- Create: `web/src/test/setup.ts`
- Create: `web/.gitignore`
- Create: `web/.prettierrc.json`
- Create: `web/.prettierignore`
- Create: `web/.eslintignore`
- Create: `web/eslint.config.mjs`
- Modify: `settings.gradle.kts`
- Modify: `build.gradle.kts`
- Modify: `.gitignore`
- Modify: `src/main/resources/static/index.html` (delete)
- Test: `web/src/App.test.tsx`

- [ ] **Step 1.1: Create `web/package.json`**

```json
{
  "name": "nocs-web",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest",
    "lint": "eslint .",
    "format": "prettier --write .",
    "format:check": "prettier --check ."
  },
  "dependencies": {
    "@tanstack/react-query": "5.59.20",
    "react": "19.0.0",
    "react-dom": "19.0.0",
    "react-router-dom": "6.28.0"
  },
  "devDependencies": {
    "@testing-library/dom": "10.4.0",
    "@testing-library/jest-dom": "6.6.3",
    "@testing-library/react": "16.1.0",
    "@testing-library/user-event": "14.5.2",
    "@types/react": "19.0.1",
    "@types/react-dom": "19.0.1",
    "@vitejs/plugin-react": "4.3.4",
    "@typescript-eslint/eslint-plugin": "8.18.1",
    "@typescript-eslint/parser": "8.18.1",
    "eslint": "9.17.0",
    "eslint-plugin-react": "7.37.2",
    "eslint-plugin-react-hooks": "5.0.0",
    "eslint-plugin-react-refresh": "0.4.16",
    "globals": "15.14.0",
    "jsdom": "25.0.1",
    "prettier": "3.4.2",
    "typescript": "5.7.2",
    "typescript-eslint": "8.18.1",
    "vite": "7.0.0",
    "vitest": "2.1.8"
  }
}
```

- [ ] **Step 1.2: Create `web/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "isolatedModules": true,
    "moduleDetection": "force",
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "types": ["vitest/globals", "@testing-library/jest-dom"],
    "baseUrl": ".",
    "paths": {
      "@/*": ["src/*"]
    }
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

- [ ] **Step 1.3: Create `web/tsconfig.node.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2023"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true,
    "strict": true,
    "noEmit": true
  },
  "include": ["vite.config.ts", "vitest.config.ts"]
}
```

- [ ] **Step 1.4: Create `web/vite.config.ts`**

```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

const backend = process.env.NOCS_BACKEND ?? "http://localhost:8080";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: backend, changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    target: "es2022",
    chunkSizeWarningLimit: 600,
  },
});
```

SSE streams over the same `/api` proxy entry, so no separate config is needed.

- [ ] **Step 1.5: Create `web/vitest.config.ts`**

```typescript
import { defineConfig, mergeConfig } from "vitest/config";
import viteConfig from "./vite.config";

export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      globals: true,
      environment: "jsdom",
      setupFiles: "./src/test/setup.ts",
      css: false,
      include: ["src/**/*.{test,spec}.{ts,tsx}"],
    },
  }),
);
```

- [ ] **Step 1.6: Create `web/index.html`**

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>NOCS</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 1.7: Create `web/public/favicon.svg`**

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
  <rect width="32" height="32" rx="6" fill="#0b1220"/>
  <circle cx="16" cy="16" r="9" fill="none" stroke="#5fb4ff" stroke-width="2"/>
  <circle cx="16" cy="16" r="2" fill="#5fb4ff"/>
</svg>
```

- [ ] **Step 1.8: Create `web/src/styles/tokens.css`**

```css
:root {
  --color-bg: #0b1220;
  --color-surface: #131b2c;
  --color-surface-2: #1a2440;
  --color-border: #25324f;
  --color-text: #e6edf7;
  --color-text-muted: #8b98b3;
  --color-accent: #5fb4ff;
  --color-success: #5cdaa6;
  --color-warning: #f1c14d;
  --color-danger: #ff6b6b;
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 24px;
  --space-6: 32px;
  --radius: 6px;
  --font-mono: ui-monospace, SFMono-Regular, Menlo, monospace;
  --font-body: system-ui, -apple-system, sans-serif;
}
```

- [ ] **Step 1.9: Create `web/src/styles/global.css`**

```css
@import "./tokens.css";

* { box-sizing: border-box; }
html, body, #root { height: 100%; margin: 0; }
body {
  background: var(--color-bg);
  color: var(--color-text);
  font-family: var(--font-body);
  font-size: 14px;
}
a { color: var(--color-accent); text-decoration: none; }
a:hover { text-decoration: underline; }
button {
  background: var(--color-surface-2);
  color: var(--color-text);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  padding: var(--space-2) var(--space-3);
  cursor: pointer;
  font: inherit;
}
button:hover:not(:disabled) { border-color: var(--color-accent); }
button:disabled { opacity: 0.5; cursor: not-allowed; }
input, select, textarea {
  background: var(--color-bg);
  color: var(--color-text);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  padding: var(--space-2) var(--space-3);
  font: inherit;
}
table { border-collapse: collapse; width: 100%; }
th, td {
  padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--color-border);
  text-align: left;
}
code, pre { font-family: var(--font-mono); }
```

- [ ] **Step 1.10: Create `web/src/main.tsx`**

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles/global.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
```

- [ ] **Step 1.11: Create `web/src/App.tsx`**

```tsx
export default function App() {
  return (
    <main style={{ padding: 16 }}>
      <h1>NOCS</h1>
      <p>web client bootstrap (Plan H)</p>
    </main>
  );
}
```

- [ ] **Step 1.12: Create `web/src/test/setup.ts`**

```typescript
import "@testing-library/jest-dom/vitest";
```

- [ ] **Step 1.13: Create `web/src/App.test.tsx` (failing test)**

```tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import App from "./App";

describe("App", () => {
  it("renders the NOCS heading", () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: /NOCS/i })).toBeInTheDocument();
  });
});
```

- [ ] **Step 1.14: Create `web/.gitignore`**

```
node_modules
dist
.vite
*.log
.eslintcache
```

- [ ] **Step 1.15: Create `web/.prettierrc.json`**

```json
{ "singleQuote": false, "semi": true, "trailingComma": "all", "printWidth": 100 }
```

- [ ] **Step 1.16: Create `web/.prettierignore` and `web/.eslintignore`**

`.prettierignore`:

```
dist
node_modules
package-lock.json
```

`.eslintignore`:

```
dist
node_modules
```

- [ ] **Step 1.17: Create `web/eslint.config.mjs`**

```javascript
import js from "@eslint/js";
import tseslint from "typescript-eslint";
import react from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import globals from "globals";

export default tseslint.config(
  { ignores: ["dist", "node_modules"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      globals: { ...globals.browser, ...globals.node },
    },
    settings: { react: { version: "19.0" } },
    plugins: {
      react,
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...react.configs.recommended.rules,
      ...reactHooks.configs.recommended.rules,
      "react/react-in-jsx-scope": "off",
      "react/prop-types": "off",
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
    },
  },
);
```

- [ ] **Step 1.18: Install dependencies and run the failing test**

Run:

```bash
cd web && npm install
npm test
```

Expected: install completes (creates `package-lock.json` and `node_modules`); `npm test` PASSES (`App` heading is rendered). The point of Step 1.13's test is to lock in the smoke; if it fails here, Step 1.11 was wrong — fix and re-run.

- [ ] **Step 1.19: Modify `settings.gradle.kts` to declare the node-gradle plugin**

Add the plugin to `pluginManagement` (create the block if absent). Existing content stays.

```kotlin
pluginManagement {
    repositories {
        gradlePluginPortal()
        mavenCentral()
    }
    plugins {
        id("com.github.node-gradle.node") version "7.1.0"
    }
}

plugins {
    id("org.gradle.toolchains.foojay-resolver-convention") version "0.10.0"
}

rootProject.name = "nocs"
```

- [ ] **Step 1.20: Modify `build.gradle.kts` — add the node plugin and wire it to `processResources`**

Add the plugin id to the existing `plugins { ... }` block:

```kotlin
plugins {
    java
    application
    id("org.springframework.boot") version "3.5.3"
    id("io.spring.dependency-management") version "1.1.6"
    id("org.beryx.runtime") version "2.0.1"
    id("com.github.node-gradle.node") version "7.1.0"
}
```

Then append (anywhere after the existing `tasks.withType<Test>` block):

```kotlin
node {
    version.set("22.12.0")
    npmVersion.set("10.9.0")
    download.set(true)
    workDir.set(layout.buildDirectory.dir("nodejs"))
    npmWorkDir.set(layout.buildDirectory.dir("npm"))
    nodeProjectDir.set(file("web"))
}

val webDist = layout.buildDirectory.dir("generated-resources/web/static")

val npmCiWeb =
    tasks.register<com.github.gradle.node.npm.task.NpmTask>("npmCiWeb") {
        group = "web"
        description = "Install web/ npm dependencies for CI builds."
        dependsOn(tasks.named("nodeSetup"))
        args.set(listOf("ci", "--no-audit", "--no-fund"))
        inputs.file("web/package.json")
        inputs.file("web/package-lock.json")
        outputs.dir("web/node_modules")
    }

val npmBuildWeb =
    tasks.register<com.github.gradle.node.npm.task.NpmTask>("npmBuildWeb") {
        group = "web"
        description = "Run vite build to produce web/dist."
        dependsOn(npmCiWeb)
        args.set(listOf("run", "build"))
        inputs.dir("web/src")
        inputs.dir("web/public")
        inputs.file("web/index.html")
        inputs.file("web/package.json")
        inputs.file("web/package-lock.json")
        inputs.file("web/tsconfig.json")
        inputs.file("web/vite.config.ts")
        outputs.dir("web/dist")
    }

val syncWebDist =
    tasks.register<Sync>("syncWebDist") {
        group = "web"
        description = "Copy web/dist into build/generated-resources/web/static for Spring."
        dependsOn(npmBuildWeb)
        from("web/dist")
        into(webDist)
    }

sourceSets.named("main") {
    resources.srcDir(syncWebDist.map { it.destinationDir })
}

tasks.named("processResources") { dependsOn(syncWebDist) }

val npmTestWeb =
    tasks.register<com.github.gradle.node.npm.task.NpmTask>("npmTestWeb") {
        group = "verification"
        description = "Run web/ Vitest suite."
        dependsOn(npmCiWeb)
        args.set(listOf("test", "--", "--run"))
        inputs.dir("web/src")
    }

val npmLintWeb =
    tasks.register<com.github.gradle.node.npm.task.NpmTask>("npmLintWeb") {
        group = "verification"
        description = "Run web/ ESLint."
        dependsOn(npmCiWeb)
        args.set(listOf("run", "lint"))
        inputs.dir("web/src")
        inputs.file("web/eslint.config.mjs")
    }

val npmFormatCheckWeb =
    tasks.register<com.github.gradle.node.npm.task.NpmTask>("npmFormatCheckWeb") {
        group = "verification"
        description = "Run web/ Prettier in --check mode."
        dependsOn(npmCiWeb)
        args.set(listOf("run", "format:check"))
        inputs.dir("web/src")
        inputs.file("web/.prettierrc.json")
    }

tasks.named("check") {
    dependsOn(npmTestWeb, npmLintWeb, npmFormatCheckWeb)
}
```

- [ ] **Step 1.21: Modify root `.gitignore`**

Add the new build output paths:

```
web/node_modules/
web/dist/
build/generated-resources/
```

(The existing ignore lines for `build/`, `.gradle/`, etc., stay as-is.)

- [ ] **Step 1.22: Delete the placeholder static index**

The Vite build emits its own `index.html`; we don't want the Plan A placeholder shadowing it.

```bash
git rm src/main/resources/static/index.html
```

- [ ] **Step 1.23: Run the Gradle wiring**

```bash
./gradlew npmCiWeb npmBuildWeb syncWebDist --info
```

Expected: node 22.12.0 is downloaded into `build/nodejs/`, `npm ci` succeeds, `vite build` writes `web/dist/index.html` plus `web/dist/assets/*.js`/`*.css`, and `syncWebDist` mirrors it into `build/generated-resources/web/static/`.

- [ ] **Step 1.24: Format the new TypeScript files**

```bash
cd web && npm run format
```

This avoids the format-check task failing the first build.

- [ ] **Step 1.25: Commit**

```bash
git add settings.gradle.kts build.gradle.kts .gitignore web/ \
  ':!src/main/resources/static/index.html' src/main/resources/static
git commit -m "feat(web): scaffold Vite+React+TS project and wire it into Gradle"
```

---

### Task 2: API client, token bootstrap, and login gate

**Files:**
- Create: `web/src/api/client.ts`
- Create: `web/src/api/token.ts`
- Create: `web/src/api/types.ts`
- Create: `web/src/auth/AuthContext.tsx`
- Create: `web/src/auth/AuthProvider.tsx`
- Create: `web/src/auth/LoginPanel.tsx`
- Create: `web/src/auth/TokenGate.tsx`
- Create: `web/src/test/render.tsx`
- Create: `web/src/test/mocks.ts`
- Modify: `web/src/App.tsx`
- Test: `web/src/api/client.test.ts`
- Test: `web/src/auth/TokenGate.test.tsx`

- [ ] **Step 2.1: Create `web/src/api/types.ts`**

These types mirror the wire formats produced by the Java DTOs. Field names use the snake_case keys that Spring serializes (we keep them snake_case on the wire, camelCase only in handler parameters).

```typescript
export type DeviceKind = "mount" | "camera" | "filterwheel" | "focuser" | "unknown";

export interface DeviceView {
  id: string;
  indiName: string;
  kind: DeviceKind;
  state: string;
  connected: boolean;
}

export interface SlewBody { raHours: number; decDegrees: number }
export interface CoolBody { setpointCelsius: number }
export interface ExposeBody {
  durationSeconds: number;
  filter?: string;
  target?: string;
  step?: string;
  seq?: number;
}
export interface MoveBody { position?: number; offset?: number }
export interface SelectSlotBody { slot: number }

export interface TargetView {
  id: string;
  primaryName: string;
  aliases: string[];
  kind: string;
  raJ2000Deg: number;
  decJ2000Deg: number;
  constellation: string;
  magnitude: number;
  sizeArcmin: number;
  notes: string;
}

export interface TargetObservation {
  altitudeDeg: number;
  azimuthDeg: number;
  airmass: number;
  hourAngleHours: number;
  transitInHours: number | null;
}

export interface TargetSearchResult {
  target: TargetView;
  observation: TargetObservation | null;
}

export interface ImageView {
  id: number;
  sessionId: number | null;
  device: string;
  filter: string;
  target: string;
  exposureSec: number;
  step: string;
  seq: number;
  fitsPath: string;
  thumbPath: string | null;
  bytes: number;
  width: number | null;
  height: number | null;
  bitpix: number | null;
  dateObs: string | null;
  createdAt: string;
}

export interface ObservatoryView {
  id: number;
  name: string;
  latitudeDeg: number;
  longitudeDeg: number;
  elevationM: number;
  timezone: string;
  horizonMaskJson: string | null;
  active: boolean;
}

export interface RuleView {
  name: string;
  action: "pause_sequence" | "abort_and_park" | "e_stop";
  when: Record<string, unknown>;
  latched: boolean;
}

export interface SafetyStatusView {
  rules: RuleView[];
  latched: string[];
  activeTargetId: string | null;
}

export interface InstallStatusView {
  installed: boolean;
  binaryPath: string | null;
  dbDir: string | null;
  dbName: string;
  ready: boolean;
  supportedPlatform: boolean;
  allowNetwork: boolean;
}

export interface InstallProgressView {
  state: string;
  message: string;
  bytesDone: number;
  bytesTotal: number;
  errorMessage: string | null;
}

export interface PlateSolutionView {
  raJ2000Deg: number;
  decJ2000Deg: number;
  rotationDeg: number;
  pixelScaleArcsec: number;
  solver: string;
  durationMs: number;
}

export interface SolveResponse {
  imageId: number;
  status: "ok" | "error";
  failureKind?: string;
  message?: string;
  durationMs?: number;
  solution?: PlateSolutionView;
}

export type SequenceStatus =
  | "PENDING"
  | "RUNNING"
  | "PAUSED"
  | "COMPLETED"
  | "ABORTED"
  | "FAILED";

export interface SequenceStepDto {
  filter: string;
  exposure_s: number;
  count: number;
  name?: string;
}

export interface PreStepDto { type: "slew_and_sync" | "autofocus" }

export interface DitherDto { enabled: boolean; pixels: number; every_n_subs: number }

export interface DeviceIdsDto {
  mount_id?: string;
  camera_id?: string;
  filter_wheel_id?: string;
  focuser_id?: string;
}

export interface SequenceDefinitionDto {
  name?: string;
  target_id?: string;
  dither?: DitherDto;
  pre_steps?: PreStepDto[];
  steps?: SequenceStepDto[];
  device_ids?: DeviceIdsDto;
}

export interface SequenceView {
  id: number;
  session_id: number | null;
  name: string;
  status: SequenceStatus;
  failure_reason: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  current_step_index: number | null;
  current_sub_index: number | null;
  subs_completed: number;
  subs_total: number;
  definition: SequenceDefinitionDto | null;
}

export interface SessionRow {
  id: number;
  name: string;
  opened_at: string;
  closed_at: string | null;
}

export interface SessionEventRow {
  id: number;
  ts: string;
  topic: string;
  type: string;
  payload_json: string | null;
}

export interface SessionDetail {
  session: SessionRow;
  events: SessionEventRow[];
}

export type EventTopic =
  | "mount" | "camera" | "filterwheel" | "focuser"
  | "sequence" | "safety" | "session" | "device_connection" | "system"
  | "target" | "sensor" | "platesolving";

export interface BusEvent<T = Record<string, unknown>> {
  topic: EventTopic;
  type: string;
  ts: string;
  payload?: T;
}
```

- [ ] **Step 2.2: Create `web/src/api/token.ts`**

```typescript
const KEY = "nocs.token";

export function getToken(): string | null {
  try { return localStorage.getItem(KEY); } catch { return null; }
}

export function setToken(token: string): void {
  localStorage.setItem(KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(KEY);
}
```

- [ ] **Step 2.3: Create `web/src/api/client.ts`**

```typescript
import { getToken } from "./token";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: unknown,
    message?: string,
  ) {
    super(message ?? `HTTP ${status}`);
    this.name = "ApiError";
  }
  isUnauthorized(): boolean { return this.status === 401; }
}

export interface ApiOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
  headers?: Record<string, string>;
}

export async function apiFetch<T>(path: string, opts: ApiOptions = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    Accept: "application/json",
    ...(opts.headers ?? {}),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";

  const res = await fetch(path, {
    method: opts.method ?? "GET",
    headers,
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
    signal: opts.signal,
  });

  if (res.status === 204) return undefined as T;

  const text = await res.text();
  let parsed: unknown = null;
  if (text) {
    try { parsed = JSON.parse(text); } catch { parsed = text; }
  }
  if (!res.ok) {
    const message =
      typeof parsed === "object" && parsed !== null && "error" in parsed
        ? String((parsed as Record<string, unknown>).error)
        : `HTTP ${res.status}`;
    throw new ApiError(res.status, parsed, message);
  }
  return parsed as T;
}

export async function apiBlob(path: string, opts: ApiOptions = {}): Promise<Blob> {
  const token = getToken();
  const headers: Record<string, string> = { ...(opts.headers ?? {}) };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(path, {
    method: opts.method ?? "GET",
    headers,
    signal: opts.signal,
  });
  if (!res.ok) throw new ApiError(res.status, null);
  return res.blob();
}
```

- [ ] **Step 2.4: Create `web/src/test/mocks.ts`**

```typescript
import { vi } from "vitest";

export interface MockResponse {
  status?: number;
  body?: unknown;
  text?: string;
  blob?: Blob;
}

export type Route = string | RegExp | ((url: string, init: RequestInit) => boolean);

export interface RouteHandler {
  match: Route;
  respond:
    | MockResponse
    | ((url: string, init: RequestInit) => MockResponse | Promise<MockResponse>);
}

export function installFetchMock(routes: RouteHandler[]) {
  const calls: { url: string; init: RequestInit }[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = typeof input === "string" ? input : input.toString();
    calls.push({ url, init });
    for (const r of routes) {
      const ok =
        typeof r.match === "function" ? r.match(url, init)
        : r.match instanceof RegExp ? r.match.test(url)
        : url.endsWith(r.match);
      if (ok) {
        const out = typeof r.respond === "function" ? await r.respond(url, init) : r.respond;
        const status = out.status ?? 200;
        const body = out.text !== undefined ? out.text : JSON.stringify(out.body ?? null);
        if (out.blob) {
          return new Response(out.blob, { status });
        }
        return new Response(body, {
          status,
          headers: { "Content-Type": "application/json" },
        });
      }
    }
    return new Response(`unhandled ${url}`, { status: 599 });
  });
  vi.stubGlobal("fetch", fn);
  return { fn, calls };
}

export function uninstallFetchMock() { vi.unstubAllGlobals(); }
```

- [ ] **Step 2.5: Create `web/src/api/client.test.ts` (failing test)**

```typescript
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { apiFetch, ApiError } from "./client";
import { setToken, clearToken } from "./token";
import { installFetchMock, uninstallFetchMock } from "@/test/mocks";

describe("apiFetch", () => {
  beforeEach(() => clearToken());
  afterEach(() => { uninstallFetchMock(); clearToken(); });

  it("attaches the bearer token", async () => {
    setToken("hunter2");
    const { calls } = installFetchMock([
      { match: "/api/config", respond: { body: { foo: "bar" } } },
    ]);
    const out = await apiFetch<Record<string, string>>("/api/config");
    expect(out).toEqual({ foo: "bar" });
    expect(calls[0].init.headers).toMatchObject({ Authorization: "Bearer hunter2" });
  });

  it("throws ApiError on 4xx with parsed body", async () => {
    installFetchMock([
      { match: "/api/safety/e-stop", respond: { status: 400, body: { error: "nope" } } },
    ]);
    await expect(apiFetch("/api/safety/e-stop", { method: "POST", body: {} }))
      .rejects.toMatchObject({ status: 400, message: "nope" } satisfies Partial<ApiError>);
  });

  it("returns undefined on 204", async () => {
    installFetchMock([
      { match: /\/api\/devices\/.*\/connect/, respond: { status: 204 } },
    ]);
    const out = await apiFetch<void>("/api/devices/mount-1/connect", { method: "POST" });
    expect(out).toBeUndefined();
  });
});
```

Run:

```bash
cd web && npm test -- --run client.test
```

Expected: PASS (the implementation in 2.3 already satisfies the contract).

- [ ] **Step 2.6: Create `web/src/auth/AuthContext.tsx`**

```tsx
import { createContext } from "react";

export interface AuthState {
  token: string | null;
  setToken: (token: string) => void;
  clearToken: () => void;
}

export const AuthContext = createContext<AuthState>({
  token: null,
  setToken: () => {},
  clearToken: () => {},
});
```

- [ ] **Step 2.7: Create `web/src/auth/AuthProvider.tsx`**

```tsx
import { useCallback, useEffect, useMemo, useState } from "react";
import { AuthContext } from "./AuthContext";
import { clearToken as drop, getToken, setToken as save } from "@/api/token";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setTokenState] = useState<string | null>(() => getToken());

  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === "nocs.token") setTokenState(e.newValue);
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const setToken = useCallback((t: string) => { save(t); setTokenState(t); }, []);
  const clearToken = useCallback(() => { drop(); setTokenState(null); }, []);

  const value = useMemo(() => ({ token, setToken, clearToken }), [token, setToken, clearToken]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
```

- [ ] **Step 2.8: Create `web/src/auth/LoginPanel.tsx`**

```tsx
import { useContext, useState } from "react";
import { AuthContext } from "./AuthContext";

export function LoginPanel() {
  const { setToken } = useContext(AuthContext);
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);

  return (
    <main style={{ maxWidth: 360, margin: "8vh auto", padding: 24 }}>
      <h1>NOCS</h1>
      <p>Enter the bearer token from <code>config.yaml</code>.</p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!value.trim()) { setError("Token is required"); return; }
          setError(null);
          setToken(value.trim());
        }}
      >
        <label style={{ display: "block", marginBottom: 8 }}>
          <span>Bearer token</span>
          <input
            type="password"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            style={{ width: "100%", marginTop: 4 }}
            autoFocus
          />
        </label>
        {error && <p style={{ color: "var(--color-danger)" }}>{error}</p>}
        <button type="submit">Sign in</button>
      </form>
    </main>
  );
}
```

- [ ] **Step 2.9: Create `web/src/auth/TokenGate.tsx`**

```tsx
import { useContext } from "react";
import { AuthContext } from "./AuthContext";
import { LoginPanel } from "./LoginPanel";

export function TokenGate({ children }: { children: React.ReactNode }) {
  const { token } = useContext(AuthContext);
  if (!token) return <LoginPanel />;
  return <>{children}</>;
}
```

- [ ] **Step 2.10: Create `web/src/test/render.tsx`**

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderOptions } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AuthProvider } from "@/auth/AuthProvider";

export function renderWithProviders(
  ui: React.ReactElement,
  options: RenderOptions & { route?: string } = {},
) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <AuthProvider>
        <MemoryRouter initialEntries={[options.route ?? "/"]}>{ui}</MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
    options,
  );
}
```

- [ ] **Step 2.11: Create `web/src/auth/TokenGate.test.tsx` (failing test)**

```tsx
import { describe, it, expect, beforeEach } from "vitest";
import userEvent from "@testing-library/user-event";
import { screen } from "@testing-library/react";
import { TokenGate } from "./TokenGate";
import { clearToken, getToken } from "@/api/token";
import { renderWithProviders } from "@/test/render";

describe("TokenGate", () => {
  beforeEach(() => clearToken());

  it("shows the login panel when no token is set", () => {
    renderWithProviders(<TokenGate><div>secret</div></TokenGate>);
    expect(screen.getByRole("heading", { name: /NOCS/i })).toBeInTheDocument();
    expect(screen.queryByText("secret")).toBeNull();
  });

  it("reveals children once a token is entered", async () => {
    renderWithProviders(<TokenGate><div>secret</div></TokenGate>);
    const input = screen.getByLabelText(/Bearer token/i);
    await userEvent.type(input, "hunter2");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByText("secret")).toBeInTheDocument();
    expect(getToken()).toBe("hunter2");
  });
});
```

Run:

```bash
cd web && npm test -- --run TokenGate
```

Expected: PASS — gating logic works end-to-end via the Auth context.

- [ ] **Step 2.12: Modify `web/src/App.tsx` to mount the gate**

Replace its body with:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "./auth/AuthProvider";
import { TokenGate } from "./auth/TokenGate";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 5_000, refetchOnWindowFocus: false, retry: 1 },
  },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <TokenGate>
          <main style={{ padding: 16 }}>
            <h1>NOCS</h1>
            <p>web client bootstrap (Plan H)</p>
          </main>
        </TokenGate>
      </AuthProvider>
    </QueryClientProvider>
  );
}
```

- [ ] **Step 2.13: Update the existing `App.test.tsx`**

The pre-existing App test asserted the heading rendered unconditionally. Now the gate hides the body until a token exists.

Replace `web/src/App.test.tsx` with:

```tsx
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import App from "./App";
import { clearToken, setToken } from "./api/token";

describe("App", () => {
  beforeEach(() => clearToken());
  afterEach(() => clearToken());

  it("shows the login panel before a token is set", () => {
    render(<App />);
    expect(screen.getByLabelText(/Bearer token/i)).toBeInTheDocument();
  });

  it("renders the bootstrap message after a token is set", () => {
    setToken("dev-token");
    render(<App />);
    expect(screen.getByText(/web client bootstrap/i)).toBeInTheDocument();
  });
});
```

Run:

```bash
cd web && npm test -- --run
```

Expected: all three test files pass (App, client, TokenGate).

- [ ] **Step 2.14: Format and commit**

```bash
cd web && npm run format
cd ..
git add web/src/api web/src/auth web/src/test web/src/App.tsx web/src/App.test.tsx
git commit -m "feat(web): add bearer-token API client and login gate"
```

---

### Task 3: SSE event stream provider, useTopic hook, and connection-status pill

**Files:**
- Create: `web/src/events/connection.ts`
- Create: `web/src/events/EventStream.tsx`
- Create: `web/src/events/useTopic.ts`
- Create: `web/src/ui/ConnectionPill.tsx`
- Test: `web/src/events/EventStream.test.tsx`
- Test: `web/src/events/useTopic.test.tsx`

> **Note:** `EventSource` does not allow a custom `Authorization` header. We solve this by passing the token as a query string (`?token=...`) and accepting it in `BearerTokenFilter`. The filter change is folded into Task 14 (where the SPA fallback also lands) so this task can stay frontend-only; until then the dev proxy works because the token check ignores `/api/events` if no header is present (see SecurityConfig — the existing chain requires authentication on `/api/**`, so the bridge step must happen before connecting in production). To keep this task green in isolation, the EventStream uses the `Authorization` header path via a `fetch`-based fallback only in tests.

A simpler workaround that also keeps production secure: ship a tiny local relay in the SPA that opens an `EventSource` against `/api/events?token=<token>`. We add token-as-query-string acceptance to the backend in Task 14.

- [ ] **Step 3.1: Create `web/src/events/connection.ts`**

```typescript
export type ConnectionState = "idle" | "connecting" | "open" | "closed" | "error";

export interface SseEnvelope {
  topic: string;
  type: string;
  ts: string;
  payload?: Record<string, unknown>;
}
```

- [ ] **Step 3.2: Create `web/src/events/EventStream.tsx`**

```tsx
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { AuthContext } from "@/auth/AuthContext";
import type { ConnectionState, SseEnvelope } from "./connection";

type Listener = (e: SseEnvelope) => void;

interface StreamApi {
  state: ConnectionState;
  subscribe: (topic: string, fn: Listener) => () => void;
  lastEvent: SseEnvelope | null;
}

const StreamContext = createContext<StreamApi>({
  state: "idle",
  subscribe: () => () => {},
  lastEvent: null,
});

export const useEventStream = () => useContext(StreamContext);

interface EventStreamProps {
  topics?: string[];
  factory?: (url: string) => EventSourceLike;
  children: ReactNode;
}

export interface EventSourceLike {
  addEventListener: (type: string, fn: (e: MessageEvent) => void) => void;
  removeEventListener: (type: string, fn: (e: MessageEvent) => void) => void;
  close: () => void;
  onopen?: ((e: Event) => void) | null;
  onerror?: ((e: Event) => void) | null;
  onmessage?: ((e: MessageEvent) => void) | null;
}

const TOPICS_DEFAULT = [
  "mount", "camera", "filterwheel", "focuser", "sequence",
  "safety", "session", "device_connection", "system",
  "target", "sensor", "platesolving",
];

export function EventStreamProvider({
  topics = TOPICS_DEFAULT,
  factory,
  children,
}: EventStreamProps) {
  const { token } = useContext(AuthContext);
  const [state, setState] = useState<ConnectionState>("idle");
  const [lastEvent, setLastEvent] = useState<SseEnvelope | null>(null);
  const listeners = useRef(new Map<string, Set<Listener>>());

  useEffect(() => {
    if (!token) { setState("idle"); return; }
    const params = new URLSearchParams();
    params.set("topics", topics.join(","));
    params.set("token", token);
    const url = `/api/events?${params.toString()}`;
    const make = factory ?? ((u: string) => new EventSource(u) as unknown as EventSourceLike);
    setState("connecting");
    const es = make(url);

    const onOpen = () => setState("open");
    const onError = () => setState("error");
    const handlers: { type: string; fn: (e: MessageEvent) => void }[] = [];

    for (const t of topics.flatMap(_eventTypesForTopic)) {
      const fn = (raw: MessageEvent) => {
        try {
          const data = JSON.parse(raw.data) as SseEnvelope;
          setLastEvent(data);
          listeners.current.get(data.topic)?.forEach((l) => l(data));
        } catch {
          // ignore malformed payloads
        }
      };
      es.addEventListener(t, fn);
      handlers.push({ type: t, fn });
    }
    es.onopen = onOpen;
    es.onerror = onError;

    return () => {
      handlers.forEach((h) => es.removeEventListener(h.type, h.fn));
      es.close();
      setState("closed");
    };
  }, [token, topics, factory]);

  const api: StreamApi = useMemo(
    () => ({
      state,
      lastEvent,
      subscribe: (topic, fn) => {
        let s = listeners.current.get(topic);
        if (!s) { s = new Set(); listeners.current.set(topic, s); }
        s.add(fn);
        return () => { s!.delete(fn); };
      },
    }),
    [state, lastEvent],
  );
  return <StreamContext.Provider value={api}>{children}</StreamContext.Provider>;
}

// Listen on the wildcard "message" plus any explicit event names the backend uses.
// The Spring backend sets `event: <type>` on every line, so we hear them by name; we also
// handle the fallback "message" in case a future emitter omits the event field.
function _eventTypesForTopic(_topic: string): string[] {
  return [
    "message",
    "device_state_changed", "connected", "disconnected",
    "exposure_started", "exposure_finished", "image_saved",
    "filter_selected", "focuser_moved",
    "sequence_started", "sequence_step", "sequence_progress",
    "sequence_paused", "sequence_resumed", "sequence_aborted",
    "sequence_completed", "sequence_failed",
    "safety_rule_triggered", "safety_rule_cleared", "e_stop", "e_stop_reset",
    "session_opened", "session_closed",
    "solve_started", "solved", "solve_failed",
    "install_progress", "install_succeeded", "install_failed",
    "active_target_changed", "sensor_reading_received",
  ];
}
```

- [ ] **Step 3.3: Create `web/src/events/useTopic.ts`**

```typescript
import { useEffect, useState } from "react";
import { useEventStream } from "./EventStream";
import type { SseEnvelope } from "./connection";

export function useTopic(topic: string, type?: string) {
  const { subscribe } = useEventStream();
  const [last, setLast] = useState<SseEnvelope | null>(null);
  useEffect(() => {
    return subscribe(topic, (e) => {
      if (!type || e.type === type) setLast(e);
    });
  }, [subscribe, topic, type]);
  return last;
}

export function useTopicCounter(topic: string) {
  const { subscribe } = useEventStream();
  const [count, setCount] = useState(0);
  useEffect(() => subscribe(topic, () => setCount((c) => c + 1)), [subscribe, topic]);
  return count;
}
```

- [ ] **Step 3.4: Create `web/src/ui/ConnectionPill.tsx`**

```tsx
import { useEventStream } from "@/events/EventStream";

const COLOR: Record<string, string> = {
  idle: "var(--color-text-muted)",
  connecting: "var(--color-warning)",
  open: "var(--color-success)",
  closed: "var(--color-text-muted)",
  error: "var(--color-danger)",
};

export function ConnectionPill() {
  const { state } = useEventStream();
  return (
    <span
      role="status"
      aria-label={`event stream ${state}`}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "2px 10px",
        borderRadius: 999,
        background: "var(--color-surface-2)",
        color: COLOR[state],
        fontFamily: "var(--font-mono)",
        fontSize: 12,
      }}
    >
      <span style={{ width: 8, height: 8, background: COLOR[state], borderRadius: 999 }} />
      {state}
    </span>
  );
}
```

- [ ] **Step 3.5: Create `web/src/events/EventStream.test.tsx` (failing test)**

```tsx
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { EventStreamProvider, EventSourceLike } from "./EventStream";
import { ConnectionPill } from "@/ui/ConnectionPill";
import { AuthProvider } from "@/auth/AuthProvider";
import { setToken, clearToken } from "@/api/token";

class FakeES implements EventSourceLike {
  static last: FakeES | null = null;
  onopen: ((e: Event) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  private listeners = new Map<string, Set<(e: MessageEvent) => void>>();
  closed = false;
  url: string;
  constructor(url: string) { this.url = url; FakeES.last = this; }
  addEventListener(type: string, fn: (e: MessageEvent) => void) {
    let s = this.listeners.get(type);
    if (!s) { s = new Set(); this.listeners.set(type, s); }
    s.add(fn);
  }
  removeEventListener(type: string, fn: (e: MessageEvent) => void) {
    this.listeners.get(type)?.delete(fn);
  }
  close() { this.closed = true; }
  emit(type: string, payload: unknown) {
    const ev = new MessageEvent(type, { data: JSON.stringify(payload) });
    this.listeners.get(type)?.forEach((fn) => fn(ev));
  }
  open() { this.onopen?.(new Event("open")); }
}

describe("EventStreamProvider", () => {
  beforeEach(() => { clearToken(); FakeES.last = null; });
  afterEach(() => clearToken());

  it("connects when a token is present and reports open state", () => {
    setToken("dev");
    render(
      <AuthProvider>
        <EventStreamProvider factory={(u) => new FakeES(u)}>
          <ConnectionPill />
        </EventStreamProvider>
      </AuthProvider>,
    );
    expect(FakeES.last?.url).toMatch(/\/api\/events\?topics=.*&token=dev/);
    act(() => FakeES.last!.open());
    expect(screen.getByRole("status")).toHaveTextContent("open");
  });

  it("stays idle without a token", () => {
    render(
      <AuthProvider>
        <EventStreamProvider factory={(u) => new FakeES(u)}>
          <ConnectionPill />
        </EventStreamProvider>
      </AuthProvider>,
    );
    expect(FakeES.last).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("idle");
  });
});
```

Run:

```bash
cd web && npm test -- --run EventStream
```

Expected: PASS.

- [ ] **Step 3.6: Create `web/src/events/useTopic.test.tsx` (failing test)**

```tsx
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { EventStreamProvider, EventSourceLike } from "./EventStream";
import { useTopic } from "./useTopic";
import { AuthProvider } from "@/auth/AuthProvider";
import { setToken, clearToken } from "@/api/token";

let captured: EventSourceLike & { emit: (t: string, p: unknown) => void } | null = null;

function makeFake(url: string) {
  const listeners = new Map<string, Set<(e: MessageEvent) => void>>();
  const fake: EventSourceLike & { emit: (t: string, p: unknown) => void } = {
    addEventListener: (t, fn) => {
      let s = listeners.get(t); if (!s) { s = new Set(); listeners.set(t, s); }
      s.add(fn);
    },
    removeEventListener: (t, fn) => listeners.get(t)?.delete(fn),
    close: () => {},
    onopen: null, onerror: null, onmessage: null,
    emit: (t, p) => listeners.get(t)?.forEach((fn) =>
      fn(new MessageEvent(t, { data: JSON.stringify(p) }))),
  };
  void url;
  captured = fake;
  return fake;
}

function Probe({ topic }: { topic: string }) {
  const ev = useTopic(topic);
  return <div data-testid="last">{ev?.type ?? "—"}</div>;
}

describe("useTopic", () => {
  beforeEach(() => { clearToken(); setToken("dev"); captured = null; });
  afterEach(() => clearToken());

  it("captures events for the requested topic", () => {
    render(
      <AuthProvider>
        <EventStreamProvider factory={makeFake}>
          <Probe topic="mount" />
        </EventStreamProvider>
      </AuthProvider>,
    );
    act(() => captured!.emit("device_state_changed", {
      topic: "mount", type: "device_state_changed", ts: "2026-04-23T00:00:00Z",
    }));
    expect(screen.getByTestId("last")).toHaveTextContent("device_state_changed");
  });
});
```

Run:

```bash
cd web && npm test -- --run useTopic
```

Expected: PASS.

- [ ] **Step 3.7: Format and commit**

```bash
cd web && npm run format
cd ..
git add web/src/events web/src/ui/ConnectionPill.tsx
git commit -m "feat(web): SSE event stream provider, useTopic hook, connection pill"
```

---

### Task 4: App shell — router, layout, NavBar, error boundary

**Files:**
- Create: `web/src/routes.tsx`
- Create: `web/src/ui/Layout.tsx`
- Create: `web/src/ui/NavBar.tsx`
- Create: `web/src/ui/ErrorBoundary.tsx`
- Create: `web/src/ui/Banner.tsx`
- Create: `web/src/ui/Card.tsx`
- Create: `web/src/views/DashboardView.tsx` (placeholder)
- Create: `web/src/views/SettingsView.tsx` (placeholder)
- Create: `web/src/views/TargetsView.tsx` (placeholder)
- Create: `web/src/views/MountView.tsx` (placeholder)
- Create: `web/src/views/PlateSolveView.tsx` (placeholder)
- Create: `web/src/views/CameraView.tsx` (placeholder)
- Create: `web/src/views/FilterWheelView.tsx` (placeholder)
- Create: `web/src/views/FocuserView.tsx` (placeholder)
- Create: `web/src/views/SequenceEditorView.tsx` (placeholder)
- Create: `web/src/views/SequenceRunnerView.tsx` (placeholder)
- Create: `web/src/views/GalleryView.tsx` (placeholder)
- Create: `web/src/views/SessionsView.tsx` (placeholder)
- Create: `web/src/views/SafetyView.tsx` (placeholder)
- Modify: `web/src/App.tsx`
- Modify: `web/src/App.test.tsx`
- Test: `web/src/ui/ErrorBoundary.test.tsx`

- [ ] **Step 4.1: Create `web/src/ui/Card.tsx`**

```tsx
export function Card({
  title, actions, children,
}: { title?: string; actions?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section
      style={{
        background: "var(--color-surface)",
        border: "1px solid var(--color-border)",
        borderRadius: "var(--radius)",
        padding: "var(--space-4)",
        marginBottom: "var(--space-4)",
      }}
    >
      {(title || actions) && (
        <header style={{
          display: "flex", justifyContent: "space-between", alignItems: "center",
          marginBottom: "var(--space-3)",
        }}>
          <h2 style={{ margin: 0, fontSize: 16 }}>{title}</h2>
          <div>{actions}</div>
        </header>
      )}
      {children}
    </section>
  );
}
```

- [ ] **Step 4.2: Create `web/src/ui/Banner.tsx`**

```tsx
export type BannerKind = "info" | "warning" | "danger" | "success";

const BG: Record<BannerKind, string> = {
  info: "var(--color-surface-2)",
  warning: "rgba(241, 193, 77, 0.15)",
  danger: "rgba(255, 107, 107, 0.18)",
  success: "rgba(92, 218, 166, 0.15)",
};
const BORDER: Record<BannerKind, string> = {
  info: "var(--color-border)",
  warning: "var(--color-warning)",
  danger: "var(--color-danger)",
  success: "var(--color-success)",
};

export function Banner({
  kind, children, action,
}: { kind: BannerKind; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div
      role="status"
      style={{
        display: "flex",
        gap: 12,
        alignItems: "center",
        justifyContent: "space-between",
        padding: "var(--space-3) var(--space-4)",
        background: BG[kind],
        borderLeft: `4px solid ${BORDER[kind]}`,
        borderRadius: "var(--radius)",
        marginBottom: "var(--space-3)",
      }}
    >
      <div>{children}</div>
      {action}
    </div>
  );
}
```

- [ ] **Step 4.3: Create `web/src/ui/ErrorBoundary.tsx`**

```tsx
import { Component, type ReactNode } from "react";

interface State { error: Error | null }

export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };
  static getDerivedStateFromError(error: Error): State { return { error }; }
  componentDidCatch(error: Error, info: unknown) {
    // eslint-disable-next-line no-console
    console.error("ErrorBoundary caught", error, info);
  }
  render() {
    if (this.state.error) {
      return (
        <main style={{ padding: 24 }}>
          <h1>Something broke.</h1>
          <pre style={{
            background: "var(--color-surface)", padding: 12,
            borderRadius: 6, overflow: "auto",
          }}>
{String(this.state.error.message ?? this.state.error)}
          </pre>
          <button onClick={() => this.setState({ error: null })}>Dismiss</button>
        </main>
      );
    }
    return this.props.children;
  }
}
```

- [ ] **Step 4.4: Create `web/src/ui/NavBar.tsx`**

```tsx
import { NavLink } from "react-router-dom";
import { useContext } from "react";
import { AuthContext } from "@/auth/AuthContext";
import { ConnectionPill } from "./ConnectionPill";

const LINKS: { to: string; label: string }[] = [
  { to: "/", label: "Dashboard" },
  { to: "/targets", label: "Targets" },
  { to: "/mount", label: "Mount" },
  { to: "/camera", label: "Camera" },
  { to: "/filter-wheel", label: "Filter wheel" },
  { to: "/focuser", label: "Focuser" },
  { to: "/plate-solve", label: "Plate solve" },
  { to: "/sequences", label: "Sequences" },
  { to: "/gallery", label: "Gallery" },
  { to: "/sessions", label: "Sessions" },
  { to: "/safety", label: "Safety" },
  { to: "/settings", label: "Settings" },
];

export function NavBar() {
  const { clearToken } = useContext(AuthContext);
  return (
    <nav
      style={{
        display: "flex",
        gap: 12,
        alignItems: "center",
        padding: "10px 16px",
        background: "var(--color-surface)",
        borderBottom: "1px solid var(--color-border)",
        position: "sticky",
        top: 0,
        zIndex: 10,
        flexWrap: "wrap",
      }}
    >
      <strong style={{ marginRight: 12 }}>NOCS</strong>
      <ul style={{ display: "flex", gap: 8, listStyle: "none", margin: 0, padding: 0, flexWrap: "wrap" }}>
        {LINKS.map((l) => (
          <li key={l.to}>
            <NavLink
              to={l.to}
              end={l.to === "/"}
              style={({ isActive }) => ({
                padding: "4px 10px",
                borderRadius: 4,
                background: isActive ? "var(--color-surface-2)" : "transparent",
                color: isActive ? "var(--color-accent)" : "var(--color-text)",
                textDecoration: "none",
              })}
            >
              {l.label}
            </NavLink>
          </li>
        ))}
      </ul>
      <span style={{ marginLeft: "auto", display: "flex", gap: 12, alignItems: "center" }}>
        <ConnectionPill />
        <button onClick={clearToken} title="Clear token and sign out">Sign out</button>
      </span>
    </nav>
  );
}
```

- [ ] **Step 4.5: Create `web/src/ui/Layout.tsx`**

```tsx
import { Outlet } from "react-router-dom";
import { NavBar } from "./NavBar";
import { ErrorBoundary } from "./ErrorBoundary";

export function Layout() {
  return (
    <>
      <NavBar />
      <main style={{ padding: 24, maxWidth: 1200, margin: "0 auto" }}>
        <ErrorBoundary>
          <Outlet />
        </ErrorBoundary>
      </main>
    </>
  );
}
```

- [ ] **Step 4.6: Create the placeholder views**

Each placeholder is a single-line component so the router builds. They are replaced with real implementations in Tasks 5–13. Use this template, swapping the component name and label:

`web/src/views/DashboardView.tsx`:
```tsx
export function DashboardView() { return <h1>Dashboard</h1>; }
```

Repeat for: `SettingsView`, `TargetsView`, `MountView`, `PlateSolveView`, `CameraView`, `FilterWheelView`, `FocuserView`, `SequenceEditorView`, `SequenceRunnerView`, `GalleryView`, `SessionsView`, `SafetyView` — each renders `<h1>{viewname}</h1>`.

(Listing all of them inline in the plan would be redundant boilerplate; create one `.tsx` per view with the same shape as `DashboardView` above. A bash one-liner if you prefer:

```bash
cd web/src/views && for v in Dashboard Settings Targets Mount PlateSolve Camera FilterWheel Focuser SequenceEditor SequenceRunner Gallery Sessions Safety; do
  cat > "${v}View.tsx" <<EOF
export function ${v}View() { return <h1>${v}</h1>; }
EOF
done
```

Re-run later overwrites are fine.)

- [ ] **Step 4.7: Create `web/src/routes.tsx`**

```tsx
import { Navigate, createBrowserRouter } from "react-router-dom";
import { Layout } from "./ui/Layout";
import { DashboardView } from "./views/DashboardView";
import { SettingsView } from "./views/SettingsView";
import { TargetsView } from "./views/TargetsView";
import { MountView } from "./views/MountView";
import { PlateSolveView } from "./views/PlateSolveView";
import { CameraView } from "./views/CameraView";
import { FilterWheelView } from "./views/FilterWheelView";
import { FocuserView } from "./views/FocuserView";
import { SequenceEditorView } from "./views/SequenceEditorView";
import { SequenceRunnerView } from "./views/SequenceRunnerView";
import { GalleryView } from "./views/GalleryView";
import { SessionsView } from "./views/SessionsView";
import { SafetyView } from "./views/SafetyView";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
    children: [
      { index: true, element: <DashboardView /> },
      { path: "targets", element: <TargetsView /> },
      { path: "mount", element: <MountView /> },
      { path: "plate-solve", element: <PlateSolveView /> },
      { path: "camera", element: <CameraView /> },
      { path: "filter-wheel", element: <FilterWheelView /> },
      { path: "focuser", element: <FocuserView /> },
      { path: "sequences", element: <SequenceEditorView /> },
      { path: "sequences/:id", element: <SequenceRunnerView /> },
      { path: "gallery", element: <GalleryView /> },
      { path: "sessions", element: <SessionsView /> },
      { path: "sessions/:id", element: <SessionsView /> },
      { path: "safety", element: <SafetyView /> },
      { path: "settings", element: <SettingsView /> },
      { path: "*", element: <Navigate to="/" replace /> },
    ],
  },
]);
```

- [ ] **Step 4.8: Modify `web/src/App.tsx` to mount the router**

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "react-router-dom";
import { AuthProvider } from "./auth/AuthProvider";
import { TokenGate } from "./auth/TokenGate";
import { EventStreamProvider } from "./events/EventStream";
import { router } from "./routes";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 5_000, refetchOnWindowFocus: false, retry: 1 },
  },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <TokenGate>
          <EventStreamProvider>
            <RouterProvider router={router} />
          </EventStreamProvider>
        </TokenGate>
      </AuthProvider>
    </QueryClientProvider>
  );
}
```

- [ ] **Step 4.9: Update `web/src/App.test.tsx` to assert nav links exist**

```tsx
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import App from "./App";
import { clearToken, setToken } from "./api/token";

describe("App shell", () => {
  beforeEach(() => { clearToken(); });
  afterEach(() => clearToken());

  it("renders the login panel without a token", () => {
    render(<App />);
    expect(screen.getByLabelText(/Bearer token/i)).toBeInTheDocument();
  });

  it("renders the navigation once a token is set", () => {
    setToken("dev");
    render(<App />);
    expect(screen.getByRole("link", { name: /Dashboard/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Sequences/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Safety/i })).toBeInTheDocument();
  });
});
```

- [ ] **Step 4.10: Create `web/src/ui/ErrorBoundary.test.tsx`**

```tsx
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ErrorBoundary } from "./ErrorBoundary";

function Boom(): JSX.Element { throw new Error("kaboom"); }

describe("ErrorBoundary", () => {
  it("renders the error UI when a child throws", () => {
    const orig = console.error;
    console.error = () => {};
    try {
      render(<ErrorBoundary><Boom /></ErrorBoundary>);
      expect(screen.getByText(/Something broke/i)).toBeInTheDocument();
      expect(screen.getByText(/kaboom/)).toBeInTheDocument();
    } finally {
      console.error = orig;
    }
  });
});
```

Run:

```bash
cd web && npm test -- --run
```

Expected: all suites pass (including the placeholder views referenced via the router).

- [ ] **Step 4.11: Format and commit**

```bash
cd web && npm run format
cd ..
git add web/src
git commit -m "feat(web): app shell with router, layout, navbar, error boundary"
```

---

### Task 5: Hardware dashboard view (devices + connect/disconnect, live state)

**Files:**
- Create: `web/src/api/endpoints/devices.ts`
- Create: `web/src/ui/DeviceStatePill.tsx`
- Create: `web/src/ui/ConfirmButton.tsx`
- Modify: `web/src/views/DashboardView.tsx`
- Test: `web/src/views/DashboardView.test.tsx`

- [ ] **Step 5.1: Create `web/src/api/endpoints/devices.ts`**

```typescript
import { apiFetch } from "../client";
import type {
  CoolBody, DeviceView, ExposeBody, MoveBody, SelectSlotBody, SlewBody,
} from "../types";

export const devicesApi = {
  list: () => apiFetch<DeviceView[]>("/api/devices"),
  connect: (id: string) => apiFetch<void>(`/api/devices/${encodeURIComponent(id)}/connect`, { method: "POST" }),
  disconnect: (id: string) => apiFetch<void>(`/api/devices/${encodeURIComponent(id)}/disconnect`, { method: "POST" }),
  slew: (id: string, body: SlewBody) =>
    apiFetch<void>(`/api/mounts/${encodeURIComponent(id)}/slew`, { method: "POST", body }),
  sync: (id: string, body: SlewBody) =>
    apiFetch<void>(`/api/mounts/${encodeURIComponent(id)}/sync`, { method: "POST", body }),
  park: (id: string) => apiFetch<void>(`/api/mounts/${encodeURIComponent(id)}/park`, { method: "POST" }),
  expose: (id: string, body: ExposeBody) =>
    apiFetch<void>(`/api/cameras/${encodeURIComponent(id)}/expose`, { method: "POST", body }),
  cool: (id: string, body: CoolBody) =>
    apiFetch<void>(`/api/cameras/${encodeURIComponent(id)}/cool`, { method: "POST", body }),
  selectSlot: (id: string, body: SelectSlotBody) =>
    apiFetch<void>(`/api/filterwheels/${encodeURIComponent(id)}/select`, { method: "POST", body }),
  move: (id: string, body: MoveBody) =>
    apiFetch<void>(`/api/focusers/${encodeURIComponent(id)}/move`, { method: "POST", body }),
};
```

- [ ] **Step 5.2: Create `web/src/ui/DeviceStatePill.tsx`**

```tsx
const STATE_COLOR: Record<string, string> = {
  IDLE: "var(--color-text-muted)",
  TRACKING: "var(--color-success)",
  COOLING: "var(--color-accent)",
  READY: "var(--color-success)",
  EXPOSING: "var(--color-accent)",
  DOWNLOADING: "var(--color-accent)",
  SLEWING: "var(--color-accent)",
  PARKING: "var(--color-warning)",
  PARKED: "var(--color-text-muted)",
  MOVING: "var(--color-accent)",
  ERROR: "var(--color-danger)",
  E_STOPPED: "var(--color-danger)",
  DISCONNECTED: "var(--color-text-muted)",
};

export function DeviceStatePill({ state }: { state: string }) {
  const color = STATE_COLOR[state] ?? "var(--color-text-muted)";
  return (
    <span style={{
      fontFamily: "var(--font-mono)",
      fontSize: 12,
      padding: "2px 8px",
      borderRadius: 999,
      background: "var(--color-surface-2)",
      color,
      border: `1px solid ${color}`,
    }}>{state}</span>
  );
}
```

- [ ] **Step 5.3: Create `web/src/ui/ConfirmButton.tsx`**

```tsx
import { useState } from "react";

export function ConfirmButton({
  label, confirmLabel = "Confirm", onConfirm, danger,
}: {
  label: string;
  confirmLabel?: string;
  onConfirm: () => void;
  danger?: boolean;
}) {
  const [armed, setArmed] = useState(false);
  return (
    <button
      onClick={() => {
        if (!armed) { setArmed(true); setTimeout(() => setArmed(false), 4000); return; }
        setArmed(false);
        onConfirm();
      }}
      style={danger && armed ? { borderColor: "var(--color-danger)", color: "var(--color-danger)" } : undefined}
    >
      {armed ? confirmLabel : label}
    </button>
  );
}
```

- [ ] **Step 5.4: Modify `web/src/views/DashboardView.tsx`**

```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { devicesApi } from "@/api/endpoints/devices";
import { useEventStream } from "@/events/EventStream";
import type { DeviceView } from "@/api/types";
import { Card } from "@/ui/Card";
import { DeviceStatePill } from "@/ui/DeviceStatePill";

export function DashboardView() {
  const qc = useQueryClient();
  const { subscribe } = useEventStream();
  const { data: devices, isLoading, error } = useQuery({
    queryKey: ["devices"],
    queryFn: devicesApi.list,
  });

  useEffect(() => {
    const topics = ["device_connection", "mount", "camera", "filterwheel", "focuser"];
    const unsubs = topics.map((t) => subscribe(t, () =>
      qc.invalidateQueries({ queryKey: ["devices"] })));
    return () => unsubs.forEach((u) => u());
  }, [subscribe, qc]);

  const connect = useMutation({
    mutationFn: (id: string) => devicesApi.connect(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["devices"] }),
  });
  const disconnect = useMutation({
    mutationFn: (id: string) => devicesApi.disconnect(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["devices"] }),
  });

  return (
    <div>
      <h1>Hardware</h1>
      <Card title="Devices">
        {isLoading && <p>Loading…</p>}
        {error && <p style={{ color: "var(--color-danger)" }}>{(error as Error).message}</p>}
        {devices && (
          <table>
            <thead>
              <tr>
                <th>ID</th><th>Kind</th><th>INDI name</th><th>State</th><th>Connected</th><th></th>
              </tr>
            </thead>
            <tbody>
              {devices.map((d: DeviceView) => (
                <tr key={d.id}>
                  <td><code>{d.id}</code></td>
                  <td>{d.kind}</td>
                  <td>{d.indiName}</td>
                  <td><DeviceStatePill state={d.state} /></td>
                  <td>{d.connected ? "yes" : "no"}</td>
                  <td>
                    {d.connected
                      ? <button onClick={() => disconnect.mutate(d.id)}>Disconnect</button>
                      : <button onClick={() => connect.mutate(d.id)}>Connect</button>}
                  </td>
                </tr>
              ))}
              {devices.length === 0 && (
                <tr><td colSpan={6} style={{ color: "var(--color-text-muted)" }}>
                  No devices reported. Check <code>nocs.indi.mode</code> in <code>config.yaml</code>.
                </td></tr>
              )}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
```

- [ ] **Step 5.5: Create `web/src/views/DashboardView.test.tsx`**

```tsx
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { renderWithProviders } from "@/test/render";
import { DashboardView } from "./DashboardView";
import { installFetchMock, uninstallFetchMock } from "@/test/mocks";
import { setToken, clearToken } from "@/api/token";

describe("DashboardView", () => {
  beforeEach(() => { clearToken(); setToken("dev"); });
  afterEach(() => { uninstallFetchMock(); clearToken(); });

  it("renders the device list and a connect button", async () => {
    installFetchMock([
      { match: "/api/devices", respond: { body: [
        { id: "mount-1", indiName: "Telescope Sim", kind: "mount", state: "IDLE", connected: false },
        { id: "cam-1", indiName: "CCD Sim", kind: "camera", state: "READY", connected: true },
      ]}},
    ]);
    const { findByText, findAllByRole } = renderWithProviders(<DashboardView />);
    expect(await findByText("mount-1")).toBeInTheDocument();
    expect(await findByText("READY")).toBeInTheDocument();
    const buttons = await findAllByRole("button", { name: /Connect|Disconnect/ });
    expect(buttons.length).toBeGreaterThanOrEqual(2);
  });

  it("shows the empty-state hint when no devices are returned", async () => {
    installFetchMock([{ match: "/api/devices", respond: { body: [] } }]);
    const { findByText } = renderWithProviders(<DashboardView />);
    expect(await findByText(/No devices reported/i)).toBeInTheDocument();
  });
});
```

Run:

```bash
cd web && npm test -- --run DashboardView
```

Expected: PASS.

- [ ] **Step 5.6: Format and commit**

```bash
cd web && npm run format
cd ..
git add web/src/api/endpoints/devices.ts web/src/ui/DeviceStatePill.tsx \
        web/src/ui/ConfirmButton.tsx web/src/views/DashboardView.tsx \
        web/src/views/DashboardView.test.tsx
git commit -m "feat(web): hardware dashboard with live device list"
```

---

### Task 6: Settings view — config key/values + observatories CRUD

**Files:**
- Create: `web/src/api/endpoints/config.ts`
- Create: `web/src/api/endpoints/observatories.ts`
- Modify: `web/src/views/SettingsView.tsx`
- Test: `web/src/views/SettingsView.test.tsx`

- [ ] **Step 6.1: Create `web/src/api/endpoints/config.ts`**

```typescript
import { apiFetch } from "../client";

export const configApi = {
  getAll: () => apiFetch<Record<string, string>>("/api/config"),
  patch: (body: Record<string, string>) =>
    apiFetch<Record<string, string>>("/api/config", { method: "PATCH", body }),
};
```

- [ ] **Step 6.2: Create `web/src/api/endpoints/observatories.ts`**

```typescript
import { apiFetch } from "../client";
import type { ObservatoryView } from "../types";

export interface CreateObservatoryBody {
  name: string;
  latitudeDeg: number;
  longitudeDeg: number;
  elevationM: number;
  timezone: string;
  horizonMaskJson?: string | null;
}

export interface UpdateObservatoryBody extends Partial<CreateObservatoryBody> {}

export const observatoriesApi = {
  list: () => apiFetch<ObservatoryView[]>("/api/observatories"),
  get: (id: number) => apiFetch<ObservatoryView>(`/api/observatories/${id}`),
  create: (body: CreateObservatoryBody) =>
    apiFetch<ObservatoryView>("/api/observatories", { method: "POST", body }),
  update: (id: number, body: UpdateObservatoryBody) =>
    apiFetch<ObservatoryView>(`/api/observatories/${id}`, { method: "PATCH", body }),
  activate: (id: number) =>
    apiFetch<{ id: number; active: boolean }>(`/api/observatories/${id}/activate`, { method: "POST" }),
  delete: (id: number) =>
    apiFetch<{ id: number; deleted: boolean }>(`/api/observatories/${id}`, { method: "DELETE" }),
};
```

- [ ] **Step 6.3: Replace `web/src/views/SettingsView.tsx`**

```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useContext, useEffect, useState } from "react";
import { configApi } from "@/api/endpoints/config";
import { observatoriesApi, CreateObservatoryBody } from "@/api/endpoints/observatories";
import { AuthContext } from "@/auth/AuthContext";
import { Card } from "@/ui/Card";

export function SettingsView() {
  const qc = useQueryClient();
  const { clearToken } = useContext(AuthContext);

  const config = useQuery({ queryKey: ["config"], queryFn: configApi.getAll });
  const observatories = useQuery({ queryKey: ["observatories"], queryFn: observatoriesApi.list });

  const patchConfig = useMutation({
    mutationFn: (body: Record<string, string>) => configApi.patch(body),
    onSuccess: (out) => qc.setQueryData(["config"], out),
  });
  const create = useMutation({
    mutationFn: (body: CreateObservatoryBody) => observatoriesApi.create(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["observatories"] }),
  });
  const activate = useMutation({
    mutationFn: (id: number) => observatoriesApi.activate(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["observatories"] }),
  });
  const remove = useMutation({
    mutationFn: (id: number) => observatoriesApi.delete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["observatories"] }),
  });

  const [draft, setDraft] = useState<Record<string, string>>({});
  useEffect(() => { if (config.data) setDraft(config.data); }, [config.data]);

  const [obs, setObs] = useState<CreateObservatoryBody>({
    name: "", latitudeDeg: 0, longitudeDeg: 0, elevationM: 0, timezone: "UTC", horizonMaskJson: null,
  });

  return (
    <div>
      <h1>Settings</h1>
      <Card title="Bearer token">
        <p>Token is stored in your browser's <code>localStorage</code>. Sign out clears it.</p>
        <button onClick={clearToken}>Sign out and re-enter token</button>
      </Card>

      <Card title="Configuration (config_kv)" actions={
        <button
          disabled={patchConfig.isPending || !config.data}
          onClick={() => patchConfig.mutate(draft)}
        >Save</button>
      }>
        {config.isLoading && <p>Loading…</p>}
        {config.data && (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr", gap: 8 }}>
            {Object.keys(draft).sort().map((k) => (
              <label key={k} style={{ display: "contents" }}>
                <code>{k}</code>
                <input
                  value={draft[k]}
                  onChange={(e) => setDraft((s) => ({ ...s, [k]: e.target.value }))}
                />
              </label>
            ))}
          </div>
        )}
        {patchConfig.error && (
          <p style={{ color: "var(--color-danger)" }}>{(patchConfig.error as Error).message}</p>
        )}
      </Card>

      <Card title="Observatories">
        {observatories.isLoading && <p>Loading…</p>}
        {observatories.data && (
          <table>
            <thead><tr>
              <th>Name</th><th>Lat</th><th>Lon</th><th>Elev (m)</th><th>TZ</th><th>Active</th><th></th>
            </tr></thead>
            <tbody>
              {observatories.data.map((o) => (
                <tr key={o.id}>
                  <td>{o.name}</td>
                  <td>{o.latitudeDeg.toFixed(4)}</td>
                  <td>{o.longitudeDeg.toFixed(4)}</td>
                  <td>{o.elevationM}</td>
                  <td>{o.timezone}</td>
                  <td>{o.active ? "yes" : ""}</td>
                  <td>
                    {!o.active && <button onClick={() => activate.mutate(o.id)}>Activate</button>}
                    <button onClick={() => remove.mutate(o.id)} style={{ marginLeft: 8 }}>Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <h3>Add observatory</h3>
        <div style={{ display: "grid", gridTemplateColumns: "120px 1fr", gap: 8 }}>
          <label style={{ display: "contents" }}><span>Name</span>
            <input value={obs.name} onChange={(e) => setObs({ ...obs, name: e.target.value })} />
          </label>
          <label style={{ display: "contents" }}><span>Latitude (°)</span>
            <input type="number" value={obs.latitudeDeg}
                   onChange={(e) => setObs({ ...obs, latitudeDeg: Number(e.target.value) })} />
          </label>
          <label style={{ display: "contents" }}><span>Longitude (°)</span>
            <input type="number" value={obs.longitudeDeg}
                   onChange={(e) => setObs({ ...obs, longitudeDeg: Number(e.target.value) })} />
          </label>
          <label style={{ display: "contents" }}><span>Elevation (m)</span>
            <input type="number" value={obs.elevationM}
                   onChange={(e) => setObs({ ...obs, elevationM: Number(e.target.value) })} />
          </label>
          <label style={{ display: "contents" }}><span>Timezone</span>
            <input value={obs.timezone}
                   onChange={(e) => setObs({ ...obs, timezone: e.target.value })} />
          </label>
        </div>
        <p>
          <button disabled={create.isPending || !obs.name}
                  onClick={() => create.mutate(obs)}>Add</button>
        </p>
      </Card>
    </div>
  );
}
```

- [ ] **Step 6.4: Create `web/src/views/SettingsView.test.tsx`**

```tsx
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "@/test/render";
import { SettingsView } from "./SettingsView";
import { installFetchMock, uninstallFetchMock } from "@/test/mocks";
import { clearToken, setToken } from "@/api/token";

describe("SettingsView", () => {
  beforeEach(() => { clearToken(); setToken("dev"); });
  afterEach(() => { uninstallFetchMock(); clearToken(); });

  it("loads config and observatories, allows activating one", async () => {
    const { calls } = installFetchMock([
      { match: "/api/config", respond: (url, init) =>
          init.method === "PATCH"
            ? { body: { foo: "bar2" } }
            : { body: { foo: "bar" } } },
      { match: "/api/observatories", respond: { body: [
          { id: 1, name: "Home", latitudeDeg: 51.5, longitudeDeg: -0.12,
            elevationM: 30, timezone: "UTC", horizonMaskJson: null, active: false },
      ]}},
      { match: /\/api\/observatories\/1\/activate/, respond: { body: { id: 1, active: true } } },
    ]);
    renderWithProviders(<SettingsView />);
    expect(await screen.findByDisplayValue("bar")).toBeInTheDocument();
    expect(await screen.findByText("Home")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Activate/i }));
    expect(calls.some((c) => c.url.endsWith("/api/observatories/1/activate"))).toBe(true);
  });
});
```

Run:

```bash
cd web && npm test -- --run SettingsView
```

Expected: PASS.

- [ ] **Step 6.5: Format and commit**

```bash
cd web && npm run format
cd ..
git add web/src/api/endpoints/config.ts web/src/api/endpoints/observatories.ts \
        web/src/views/SettingsView.tsx web/src/views/SettingsView.test.tsx
git commit -m "feat(web): settings view with config and observatories CRUD"
```

---

### Task 7: Target search and details view

**Files:**
- Create: `web/src/api/endpoints/targets.ts`
- Modify: `web/src/views/TargetsView.tsx`
- Test: `web/src/views/TargetsView.test.tsx`

- [ ] **Step 7.1: Create `web/src/api/endpoints/targets.ts`**

```typescript
import { apiFetch } from "../client";
import type { TargetSearchResult } from "../types";

export const targetsApi = {
  search: (q: string, limit = 20) =>
    apiFetch<TargetSearchResult[]>(
      `/api/targets/search?q=${encodeURIComponent(q)}&limit=${limit}`,
    ),
  get: (id: string) => apiFetch<TargetSearchResult>(`/api/targets/${encodeURIComponent(id)}`),
  addCustom: (body: { name: string; raJ2000Deg: number; decJ2000Deg: number; notes?: string }) =>
    apiFetch<{ id: number; targetId: string }>("/api/targets/custom", { method: "POST", body }),
};
```

- [ ] **Step 7.2: Replace `web/src/views/TargetsView.tsx`**

```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { targetsApi } from "@/api/endpoints/targets";
import { devicesApi } from "@/api/endpoints/devices";
import { Card } from "@/ui/Card";
import type { TargetSearchResult } from "@/api/types";

export function TargetsView() {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [submitted, setSubmitted] = useState<string | null>(null);
  const [selected, setSelected] = useState<TargetSearchResult | null>(null);
  const [mountId, setMountId] = useState("");

  const devices = useQuery({ queryKey: ["devices"], queryFn: devicesApi.list });
  const search = useQuery({
    queryKey: ["targets", "search", submitted],
    queryFn: () => targetsApi.search(submitted!),
    enabled: !!submitted,
  });

  const slew = useMutation({
    mutationFn: (args: { id: string; ra: number; dec: number }) =>
      devicesApi.slew(args.id, { raHours: args.ra, decDegrees: args.dec }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["devices"] }),
  });
  const sync = useMutation({
    mutationFn: (args: { id: string; ra: number; dec: number }) =>
      devicesApi.sync(args.id, { raHours: args.ra, decDegrees: args.dec }),
  });

  return (
    <div>
      <h1>Targets</h1>
      <Card title="Search">
        <form onSubmit={(e) => { e.preventDefault(); setSubmitted(q.trim()); }}
              style={{ display: "flex", gap: 8 }}>
          <input
            value={q} onChange={(e) => setQ(e.target.value)}
            placeholder="M31, NGC 7000, Vega…" autoFocus
            style={{ flex: 1 }}
          />
          <button type="submit">Search</button>
        </form>
        {search.isLoading && <p>Loading…</p>}
        {search.error && (
          <p style={{ color: "var(--color-danger)" }}>{(search.error as Error).message}</p>
        )}
        {search.data && (
          <table>
            <thead><tr><th>ID</th><th>Name</th><th>Kind</th><th>Mag</th><th>RA (h)</th><th>Dec (°)</th></tr></thead>
            <tbody>
              {search.data.map((r) => (
                <tr key={r.target.id}
                    onClick={() => setSelected(r)}
                    style={{
                      cursor: "pointer",
                      background: selected?.target.id === r.target.id ? "var(--color-surface-2)" : undefined,
                    }}>
                  <td><code>{r.target.id}</code></td>
                  <td>{r.target.primaryName}</td>
                  <td>{r.target.kind}</td>
                  <td>{Number.isFinite(r.target.magnitude) ? r.target.magnitude.toFixed(2) : "—"}</td>
                  <td>{(r.target.raJ2000Deg / 15).toFixed(3)}</td>
                  <td>{r.target.decJ2000Deg.toFixed(3)}</td>
                </tr>
              ))}
              {search.data.length === 0 && (
                <tr><td colSpan={6} style={{ color: "var(--color-text-muted)" }}>
                  No matches.
                </td></tr>
              )}
            </tbody>
          </table>
        )}
      </Card>

      {selected && (
        <Card title={`Details: ${selected.target.primaryName}`}>
          <table>
            <tbody>
              <tr><th>RA (J2000)</th><td>{(selected.target.raJ2000Deg / 15).toFixed(4)} h</td></tr>
              <tr><th>Dec (J2000)</th><td>{selected.target.decJ2000Deg.toFixed(4)} °</td></tr>
              <tr><th>Constellation</th><td>{selected.target.constellation || "—"}</td></tr>
              <tr><th>Notes</th><td>{selected.target.notes || "—"}</td></tr>
              {selected.observation && (
                <>
                  <tr><th>Altitude</th><td>{selected.observation.altitudeDeg.toFixed(2)} °</td></tr>
                  <tr><th>Azimuth</th><td>{selected.observation.azimuthDeg.toFixed(2)} °</td></tr>
                  <tr><th>Airmass</th><td>{selected.observation.airmass.toFixed(3)}</td></tr>
                  <tr><th>Hour angle</th><td>{selected.observation.hourAngleHours.toFixed(3)} h</td></tr>
                  <tr><th>Time to transit</th>
                      <td>{selected.observation.transitInHours == null
                          ? "—"
                          : `${selected.observation.transitInHours.toFixed(2)} h`}</td></tr>
                </>
              )}
            </tbody>
          </table>
          <div style={{ marginTop: 12, display: "flex", gap: 8, alignItems: "center" }}>
            <label>Mount:&nbsp;
              <select value={mountId} onChange={(e) => setMountId(e.target.value)}>
                <option value="">— select —</option>
                {(devices.data ?? []).filter((d) => d.kind === "mount").map((m) =>
                  <option key={m.id} value={m.id}>{m.id}</option>)}
              </select>
            </label>
            <button
              disabled={!mountId || slew.isPending}
              onClick={() => slew.mutate({
                id: mountId,
                ra: selected.target.raJ2000Deg / 15,
                dec: selected.target.decJ2000Deg,
              })}
            >Slew</button>
            <button
              disabled={!mountId || sync.isPending}
              onClick={() => sync.mutate({
                id: mountId,
                ra: selected.target.raJ2000Deg / 15,
                dec: selected.target.decJ2000Deg,
              })}
            >Sync</button>
          </div>
          {slew.error && <p style={{ color: "var(--color-danger)" }}>{(slew.error as Error).message}</p>}
        </Card>
      )}
    </div>
  );
}
```

- [ ] **Step 7.3: Create `web/src/views/TargetsView.test.tsx`**

```tsx
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "@/test/render";
import { TargetsView } from "./TargetsView";
import { installFetchMock, uninstallFetchMock } from "@/test/mocks";
import { clearToken, setToken } from "@/api/token";

describe("TargetsView", () => {
  beforeEach(() => { clearToken(); setToken("dev"); });
  afterEach(() => { uninstallFetchMock(); clearToken(); });

  it("searches and shows details with a slew button bound to a mount", async () => {
    const { calls } = installFetchMock([
      { match: "/api/devices", respond: { body: [
        { id: "mount-1", indiName: "TelescopeSim", kind: "mount", state: "IDLE", connected: true },
      ]}},
      { match: /\/api\/targets\/search\?q=M31/, respond: { body: [{
        target: {
          id: "messier:M31", primaryName: "Andromeda Galaxy", aliases: ["M31"],
          kind: "GALAXY", raJ2000Deg: 10.6847, decJ2000Deg: 41.2687,
          constellation: "And", magnitude: 3.4, sizeArcmin: 190.0, notes: "",
        },
        observation: { altitudeDeg: 45, azimuthDeg: 90, airmass: 1.4,
          hourAngleHours: 2.3, transitInHours: 1.1 },
      }]}},
      { match: /\/api\/mounts\/mount-1\/slew/, respond: { status: 204 } },
    ]);
    renderWithProviders(<TargetsView />);
    await userEvent.type(screen.getByPlaceholderText(/M31/), "M31");
    await userEvent.click(screen.getByRole("button", { name: /search/i }));
    await userEvent.click(await screen.findByText("Andromeda Galaxy"));
    await userEvent.selectOptions(screen.getByRole("combobox"), "mount-1");
    await userEvent.click(screen.getByRole("button", { name: /^Slew$/ }));
    expect(calls.some((c) => c.url.endsWith("/api/mounts/mount-1/slew"))).toBe(true);
  });
});
```

Run:

```bash
cd web && npm test -- --run TargetsView
```

Expected: PASS.

- [ ] **Step 7.4: Format and commit**

```bash
cd web && npm run format
cd ..
git add web/src/api/endpoints/targets.ts web/src/views/TargetsView.tsx \
        web/src/views/TargetsView.test.tsx
git commit -m "feat(web): target search and details with slew/sync"
```

---

### Task 8: Mount control + plate-solve panel

**Files:**
- Create: `web/src/api/endpoints/platesolving.ts`
- Modify: `web/src/views/MountView.tsx`
- Modify: `web/src/views/PlateSolveView.tsx`
- Test: `web/src/views/MountView.test.tsx`
- Test: `web/src/views/PlateSolveView.test.tsx`

- [ ] **Step 8.1: Create `web/src/api/endpoints/platesolving.ts`**

```typescript
import { apiFetch } from "../client";
import type { InstallProgressView, InstallStatusView, SolveResponse } from "../types";

export interface SolveBody {
  imageId: number;
  raHintHours?: number | null;
  decHintDeg?: number | null;
  radiusDeg?: number | null;
  scaleHintArcsecPerPx?: number | null;
  timeoutSec?: number | null;
}

export const plateSolvingApi = {
  solve: (body: SolveBody) =>
    apiFetch<SolveResponse>("/api/platesolving/solve", { method: "POST", body }),
  installStatus: () => apiFetch<InstallStatusView>("/api/platesolving/install"),
  installProgress: () => apiFetch<InstallProgressView>("/api/platesolving/install/progress"),
  startInstall: (acceptLicense: boolean) =>
    apiFetch<void>("/api/platesolving/install", { method: "POST", body: { acceptLicense } }),
};
```

- [ ] **Step 8.2: Replace `web/src/views/MountView.tsx`**

```tsx
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { devicesApi } from "@/api/endpoints/devices";
import { Card } from "@/ui/Card";
import { DeviceStatePill } from "@/ui/DeviceStatePill";
import { useTopic } from "@/events/useTopic";

export function MountView() {
  const devices = useQuery({ queryKey: ["devices"], queryFn: devicesApi.list });
  useTopic("mount");
  useTopic("device_connection");

  const mounts = (devices.data ?? []).filter((d) => d.kind === "mount");
  const [mountId, setMountId] = useState<string>("");
  useEffect(() => {
    if (!mountId && mounts.length === 1) setMountId(mounts[0].id);
  }, [mounts, mountId]);

  const [ra, setRa] = useState("0.000");
  const [dec, setDec] = useState("0.0");

  const slew = useMutation({
    mutationFn: () => devicesApi.slew(mountId, { raHours: Number(ra), decDegrees: Number(dec) }),
  });
  const sync = useMutation({
    mutationFn: () => devicesApi.sync(mountId, { raHours: Number(ra), decDegrees: Number(dec) }),
  });
  const park = useMutation({ mutationFn: () => devicesApi.park(mountId) });

  return (
    <div>
      <h1>Mount</h1>
      <Card title="Select mount">
        <select value={mountId} onChange={(e) => setMountId(e.target.value)}>
          <option value="">—</option>
          {mounts.map((m) => <option key={m.id} value={m.id}>{m.id}</option>)}
        </select>
        {mountId && mounts.find((m) => m.id === mountId) && (
          <span style={{ marginLeft: 12 }}>
            <DeviceStatePill state={mounts.find((m) => m.id === mountId)!.state} />
          </span>
        )}
      </Card>

      <Card title="Manual control">
        <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: 8 }}>
          <label style={{ display: "contents" }}>
            <span>RA (hours, 0–24)</span>
            <input type="number" step="0.001" value={ra}
                   onChange={(e) => setRa(e.target.value)} />
          </label>
          <label style={{ display: "contents" }}>
            <span>Dec (degrees, −90–90)</span>
            <input type="number" step="0.01" value={dec}
                   onChange={(e) => setDec(e.target.value)} />
          </label>
        </div>
        <p>
          <button disabled={!mountId || slew.isPending} onClick={() => slew.mutate()}>Slew</button>{" "}
          <button disabled={!mountId || sync.isPending} onClick={() => sync.mutate()}>Sync</button>{" "}
          <button disabled={!mountId || park.isPending} onClick={() => park.mutate()}>Park</button>
        </p>
        {slew.error && <p style={{ color: "var(--color-danger)" }}>{(slew.error as Error).message}</p>}
      </Card>
    </div>
  );
}
```

- [ ] **Step 8.3: Replace `web/src/views/PlateSolveView.tsx`**

```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { plateSolvingApi } from "@/api/endpoints/platesolving";
import { imagesApi } from "@/api/endpoints/images";
import { Card } from "@/ui/Card";
import { useTopic } from "@/events/useTopic";

export function PlateSolveView() {
  const qc = useQueryClient();
  const status = useQuery({
    queryKey: ["plateInstallStatus"],
    queryFn: plateSolvingApi.installStatus,
  });
  const progress = useQuery({
    queryKey: ["plateInstallProgress"],
    queryFn: plateSolvingApi.installProgress,
    refetchInterval: 2000,
  });
  const images = useQuery({
    queryKey: ["images", { limit: 50 }],
    queryFn: () => imagesApi.list({ limit: 50, offset: 0 }),
  });
  useTopic("platesolving");
  useEffect(() => {
    qc.invalidateQueries({ queryKey: ["plateInstallStatus"] });
  }, [progress.data?.state, qc]);

  const [imageId, setImageId] = useState<number | null>(null);
  const [accept, setAccept] = useState(false);

  const solve = useMutation({
    mutationFn: () => plateSolvingApi.solve({ imageId: imageId! }),
  });
  const install = useMutation({
    mutationFn: () => plateSolvingApi.startInstall(accept),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["plateInstallProgress"] }),
  });

  return (
    <div>
      <h1>Plate solving</h1>

      <Card title="ASTAP installation">
        {status.data && (
          <ul>
            <li><b>Installed:</b> {status.data.installed ? "yes" : "no"}</li>
            <li><b>Ready:</b> {status.data.ready ? "yes" : "no"}</li>
            <li><b>Binary:</b> <code>{status.data.binaryPath ?? "—"}</code></li>
            <li><b>DB dir:</b> <code>{status.data.dbDir ?? "—"}</code></li>
            <li><b>DB:</b> {status.data.dbName}</li>
            <li><b>Supported platform:</b> {status.data.supportedPlatform ? "yes" : "no"}</li>
            <li><b>Network installs allowed:</b> {status.data.allowNetwork ? "yes" : "no"}</li>
          </ul>
        )}
        {!status.data?.ready && status.data?.allowNetwork && (
          <>
            <label>
              <input type="checkbox" checked={accept} onChange={(e) => setAccept(e.target.checked)} />
              {" "}I accept the ASTAP license terms
            </label>
            <p><button disabled={!accept || install.isPending} onClick={() => install.mutate()}>
              Fetch & install ASTAP + DB
            </button></p>
          </>
        )}
        {progress.data && progress.data.state !== "IDLE" && (
          <p>
            <code>{progress.data.state}</code> — {progress.data.message}
            {progress.data.bytesTotal > 0 && ` (${progress.data.bytesDone}/${progress.data.bytesTotal} bytes)`}
            {progress.data.errorMessage && (
              <span style={{ color: "var(--color-danger)" }}> · {progress.data.errorMessage}</span>
            )}
          </p>
        )}
      </Card>

      <Card title="Solve a recent image">
        <label>
          Image:&nbsp;
          <select value={imageId ?? ""} onChange={(e) => setImageId(e.target.value ? Number(e.target.value) : null)}>
            <option value="">— select —</option>
            {(images.data ?? []).map((i) =>
              <option key={i.id} value={i.id}>
                #{i.id} · {i.target} · {i.filter} · {i.exposureSec}s
              </option>)}
          </select>
        </label>
        <p><button disabled={!imageId || solve.isPending} onClick={() => solve.mutate()}>
          Solve
        </button></p>
        {solve.data?.solution && (
          <pre>{JSON.stringify(solve.data.solution, null, 2)}</pre>
        )}
        {solve.data?.status === "error" && (
          <p style={{ color: "var(--color-danger)" }}>
            {solve.data.failureKind}: {solve.data.message}
          </p>
        )}
      </Card>
    </div>
  );
}
```

> The above references `imagesApi.list` from `@/api/endpoints/images`, which is created in Task 11. To keep this task green standalone, also add a one-line stub now — Task 11 fills it in.

- [ ] **Step 8.4: Create `web/src/api/endpoints/images.ts` (stub used here, expanded in Task 11)**

```typescript
import { apiFetch } from "../client";
import type { ImageView } from "../types";

export interface ImageListFilters {
  device?: string;
  session_id?: number;
  target?: string;
  filter?: string;
  limit?: number;
  offset?: number;
}

function qs(filters: ImageListFilters): string {
  const p = new URLSearchParams();
  Object.entries(filters).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  });
  const s = p.toString();
  return s ? `?${s}` : "";
}

export const imagesApi = {
  list: (filters: ImageListFilters = {}) =>
    apiFetch<ImageView[]>(`/api/images${qs(filters)}`),
};
```

- [ ] **Step 8.5: Create `web/src/views/MountView.test.tsx`**

```tsx
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "@/test/render";
import { MountView } from "./MountView";
import { installFetchMock, uninstallFetchMock } from "@/test/mocks";
import { clearToken, setToken } from "@/api/token";

describe("MountView", () => {
  beforeEach(() => { clearToken(); setToken("dev"); });
  afterEach(() => { uninstallFetchMock(); clearToken(); });

  it("auto-selects the only mount and parks it", async () => {
    const { calls } = installFetchMock([
      { match: "/api/devices", respond: { body: [
        { id: "mount-1", indiName: "TelescopeSim", kind: "mount", state: "TRACKING", connected: true },
      ]}},
      { match: /\/api\/mounts\/mount-1\/park/, respond: { status: 204 } },
    ]);
    renderWithProviders(<MountView />);
    expect(await screen.findByText("TRACKING")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /^Park$/ }));
    expect(calls.some((c) => c.url.endsWith("/api/mounts/mount-1/park"))).toBe(true);
  });
});
```

- [ ] **Step 8.6: Create `web/src/views/PlateSolveView.test.tsx`**

```tsx
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "@/test/render";
import { PlateSolveView } from "./PlateSolveView";
import { installFetchMock, uninstallFetchMock } from "@/test/mocks";
import { clearToken, setToken } from "@/api/token";

describe("PlateSolveView", () => {
  beforeEach(() => { clearToken(); setToken("dev"); });
  afterEach(() => { uninstallFetchMock(); clearToken(); });

  it("shows installation status and triggers solve on a chosen image", async () => {
    const { calls } = installFetchMock([
      { match: "/api/platesolving/install", respond: (url, init) => {
        if (init.method === "POST") return { status: 202 };
        return { body: {
          installed: true, ready: true, binaryPath: "/x/astap_cli",
          dbDir: "/x/db", dbName: "H18", supportedPlatform: true, allowNetwork: false,
        } };
      } },
      { match: "/api/platesolving/install/progress", respond: { body: {
        state: "IDLE", message: "", bytesDone: 0, bytesTotal: 0, errorMessage: null,
      } } },
      { match: /\/api\/images/, respond: { body: [
        { id: 7, sessionId: null, device: "cam-1", filter: "L", target: "M31",
          exposureSec: 5, step: "L", seq: 0, fitsPath: "/p", thumbPath: "/t",
          bytes: 100, width: 1, height: 1, bitpix: 16, dateObs: "2026", createdAt: "2026" },
      ]}},
      { match: "/api/platesolving/solve", respond: { body: {
        imageId: 7, status: "ok",
        solution: { raJ2000Deg: 10, decJ2000Deg: 41, rotationDeg: 0,
          pixelScaleArcsec: 1, solver: "astap", durationMs: 100 },
      }}},
    ]);
    renderWithProviders(<PlateSolveView />);
    expect(await screen.findByText(/H18/)).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByRole("combobox"), "7");
    await userEvent.click(screen.getByRole("button", { name: /Solve/ }));
    expect(await screen.findByText(/raJ2000Deg/)).toBeInTheDocument();
    expect(calls.some((c) => c.url.endsWith("/api/platesolving/solve"))).toBe(true);
  });
});
```

Run:

```bash
cd web && npm test -- --run MountView PlateSolveView
```

Expected: both PASS.

- [ ] **Step 8.7: Format and commit**

```bash
cd web && npm run format
cd ..
git add web/src/api/endpoints/platesolving.ts web/src/api/endpoints/images.ts \
        web/src/views/MountView.tsx web/src/views/MountView.test.tsx \
        web/src/views/PlateSolveView.tsx web/src/views/PlateSolveView.test.tsx
git commit -m "feat(web): mount control panel and plate-solve view"
```

---

### Task 9: Camera, filter wheel, focuser, autofocus controls

**Files:**
- Modify: `web/src/views/CameraView.tsx`
- Modify: `web/src/views/FilterWheelView.tsx`
- Modify: `web/src/views/FocuserView.tsx`
- Test: `web/src/views/CameraView.test.tsx`
- Test: `web/src/views/FocuserView.test.tsx`
- Test: `web/src/views/FilterWheelView.test.tsx`

- [ ] **Step 9.1: Replace `web/src/views/CameraView.tsx`**

```tsx
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { devicesApi } from "@/api/endpoints/devices";
import { Card } from "@/ui/Card";
import { DeviceStatePill } from "@/ui/DeviceStatePill";
import { useTopic } from "@/events/useTopic";

export function CameraView() {
  const devices = useQuery({ queryKey: ["devices"], queryFn: devicesApi.list });
  useTopic("camera");
  const cams = (devices.data ?? []).filter((d) => d.kind === "camera");
  const [id, setId] = useState("");
  useEffect(() => { if (!id && cams.length === 1) setId(cams[0].id); }, [cams, id]);

  const [duration, setDuration] = useState("5");
  const [filter, setFilter] = useState("");
  const [target, setTarget] = useState("");
  const [setpoint, setSetpoint] = useState("-10");

  const expose = useMutation({
    mutationFn: () => devicesApi.expose(id, {
      durationSeconds: Number(duration),
      filter: filter || undefined,
      target: target || undefined,
    }),
  });
  const cool = useMutation({
    mutationFn: () => devicesApi.cool(id, { setpointCelsius: Number(setpoint) }),
  });

  const cam = cams.find((c) => c.id === id);

  return (
    <div>
      <h1>Camera</h1>
      <Card title="Select camera">
        <select value={id} onChange={(e) => setId(e.target.value)}>
          <option value="">—</option>
          {cams.map((c) => <option key={c.id} value={c.id}>{c.id}</option>)}
        </select>
        {cam && <span style={{ marginLeft: 12 }}><DeviceStatePill state={cam.state} /></span>}
      </Card>

      <Card title="Expose">
        <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: 8 }}>
          <label style={{ display: "contents" }}>
            <span>Duration (s)</span>
            <input type="number" step="0.1" value={duration}
                   onChange={(e) => setDuration(e.target.value)} />
          </label>
          <label style={{ display: "contents" }}>
            <span>Filter (optional)</span>
            <input value={filter} onChange={(e) => setFilter(e.target.value)} />
          </label>
          <label style={{ display: "contents" }}>
            <span>Target (optional)</span>
            <input value={target} onChange={(e) => setTarget(e.target.value)} />
          </label>
        </div>
        <p><button disabled={!id || expose.isPending} onClick={() => expose.mutate()}>Expose</button></p>
      </Card>

      <Card title="Cooling">
        <label>Setpoint (°C):&nbsp;
          <input type="number" step="0.1" value={setpoint}
                 onChange={(e) => setSetpoint(e.target.value)} />
        </label>{" "}
        <button disabled={!id || cool.isPending} onClick={() => cool.mutate()}>Set cooling</button>
      </Card>
    </div>
  );
}
```

- [ ] **Step 9.2: Replace `web/src/views/FilterWheelView.tsx`**

```tsx
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { devicesApi } from "@/api/endpoints/devices";
import { Card } from "@/ui/Card";
import { DeviceStatePill } from "@/ui/DeviceStatePill";
import { useTopic } from "@/events/useTopic";

export function FilterWheelView() {
  const devices = useQuery({ queryKey: ["devices"], queryFn: devicesApi.list });
  useTopic("filterwheel");
  const wheels = (devices.data ?? []).filter((d) => d.kind === "filterwheel");
  const [id, setId] = useState("");
  useEffect(() => { if (!id && wheels.length === 1) setId(wheels[0].id); }, [wheels, id]);
  const [slot, setSlot] = useState("1");
  const select = useMutation({
    mutationFn: () => devicesApi.selectSlot(id, { slot: Number(slot) }),
  });
  const wheel = wheels.find((w) => w.id === id);

  return (
    <div>
      <h1>Filter wheel</h1>
      <Card title="Select filter wheel">
        <select value={id} onChange={(e) => setId(e.target.value)}>
          <option value="">—</option>
          {wheels.map((w) => <option key={w.id} value={w.id}>{w.id}</option>)}
        </select>
        {wheel && <span style={{ marginLeft: 12 }}><DeviceStatePill state={wheel.state} /></span>}
      </Card>
      <Card title="Move to slot">
        <label>Slot:&nbsp;
          <input type="number" min={1} value={slot} onChange={(e) => setSlot(e.target.value)} />
        </label>{" "}
        <button disabled={!id || select.isPending} onClick={() => select.mutate()}>Select</button>
      </Card>
    </div>
  );
}
```

- [ ] **Step 9.3: Replace `web/src/views/FocuserView.tsx`**

```tsx
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { devicesApi } from "@/api/endpoints/devices";
import { Card } from "@/ui/Card";
import { DeviceStatePill } from "@/ui/DeviceStatePill";
import { useTopic } from "@/events/useTopic";

export function FocuserView() {
  const devices = useQuery({ queryKey: ["devices"], queryFn: devicesApi.list });
  useTopic("focuser");
  const focs = (devices.data ?? []).filter((d) => d.kind === "focuser");
  const [id, setId] = useState("");
  useEffect(() => { if (!id && focs.length === 1) setId(focs[0].id); }, [focs, id]);

  const [absolute, setAbsolute] = useState("0");
  const [offset, setOffset] = useState("0");

  const moveAbs = useMutation({
    mutationFn: () => devicesApi.move(id, { position: Number(absolute) }),
  });
  const moveRel = useMutation({
    mutationFn: () => devicesApi.move(id, { offset: Number(offset) }),
  });

  const f = focs.find((x) => x.id === id);

  return (
    <div>
      <h1>Focuser</h1>
      <Card title="Select focuser">
        <select value={id} onChange={(e) => setId(e.target.value)}>
          <option value="">—</option>
          {focs.map((x) => <option key={x.id} value={x.id}>{x.id}</option>)}
        </select>
        {f && <span style={{ marginLeft: 12 }}><DeviceStatePill state={f.state} /></span>}
      </Card>

      <Card title="Move (absolute)">
        <input type="number" value={absolute} onChange={(e) => setAbsolute(e.target.value)} />{" "}
        <button disabled={!id || moveAbs.isPending} onClick={() => moveAbs.mutate()}>Move to</button>
      </Card>

      <Card title="Move (relative)">
        <input type="number" value={offset} onChange={(e) => setOffset(e.target.value)} />{" "}
        <button disabled={!id || moveRel.isPending} onClick={() => moveRel.mutate()}>Move by</button>
      </Card>

      <Card title="Autofocus">
        <p>v0.1 ships the no-op autofocus strategy. The Sequence engine runs it as a pre-step;
           a manual trigger here is reserved for v0.2 (`sweep`).</p>
        <button disabled>Run autofocus (v0.2)</button>
      </Card>
    </div>
  );
}
```

- [ ] **Step 9.4: Tests**

Create `web/src/views/CameraView.test.tsx`:

```tsx
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "@/test/render";
import { CameraView } from "./CameraView";
import { installFetchMock, uninstallFetchMock } from "@/test/mocks";
import { clearToken, setToken } from "@/api/token";

describe("CameraView", () => {
  beforeEach(() => { clearToken(); setToken("dev"); });
  afterEach(() => { uninstallFetchMock(); clearToken(); });

  it("exposes the only camera with chosen duration", async () => {
    const { calls } = installFetchMock([
      { match: "/api/devices", respond: { body: [
        { id: "cam-1", indiName: "CCD Sim", kind: "camera", state: "READY", connected: true },
      ]}},
      { match: /\/api\/cameras\/cam-1\/expose/, respond: { status: 204 } },
    ]);
    renderWithProviders(<CameraView />);
    await screen.findByText("READY");
    await userEvent.click(screen.getByRole("button", { name: /^Expose$/ }));
    const ex = calls.find((c) => c.url.endsWith("/api/cameras/cam-1/expose"))!;
    expect(JSON.parse(String(ex.init.body))).toMatchObject({ durationSeconds: 5 });
  });
});
```

Create `web/src/views/FilterWheelView.test.tsx`:

```tsx
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "@/test/render";
import { FilterWheelView } from "./FilterWheelView";
import { installFetchMock, uninstallFetchMock } from "@/test/mocks";
import { clearToken, setToken } from "@/api/token";

describe("FilterWheelView", () => {
  beforeEach(() => { clearToken(); setToken("dev"); });
  afterEach(() => { uninstallFetchMock(); clearToken(); });

  it("selects a slot on the only wheel", async () => {
    const { calls } = installFetchMock([
      { match: "/api/devices", respond: { body: [
        { id: "wh-1", indiName: "WheelSim", kind: "filterwheel", state: "IDLE", connected: true },
      ]}},
      { match: /\/api\/filterwheels\/wh-1\/select/, respond: { status: 204 } },
    ]);
    renderWithProviders(<FilterWheelView />);
    await screen.findByText("IDLE");
    await userEvent.click(screen.getByRole("button", { name: /^Select$/ }));
    const c = calls.find((x) => x.url.endsWith("/api/filterwheels/wh-1/select"))!;
    expect(JSON.parse(String(c.init.body))).toEqual({ slot: 1 });
  });
});
```

Create `web/src/views/FocuserView.test.tsx`:

```tsx
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "@/test/render";
import { FocuserView } from "./FocuserView";
import { installFetchMock, uninstallFetchMock } from "@/test/mocks";
import { clearToken, setToken } from "@/api/token";

describe("FocuserView", () => {
  beforeEach(() => { clearToken(); setToken("dev"); });
  afterEach(() => { uninstallFetchMock(); clearToken(); });

  it("submits a relative move", async () => {
    const { calls } = installFetchMock([
      { match: "/api/devices", respond: { body: [
        { id: "f-1", indiName: "FocSim", kind: "focuser", state: "IDLE", connected: true },
      ]}},
      { match: /\/api\/focusers\/f-1\/move/, respond: { status: 204 } },
    ]);
    renderWithProviders(<FocuserView />);
    await screen.findByText("IDLE");
    // The first number input is "absolute", the second is "offset" — pick by index.
    const offsetInput = screen.getAllByRole("spinbutton")[1];
    await userEvent.clear(offsetInput);
    await userEvent.type(offsetInput, "50");
    await userEvent.click(screen.getByRole("button", { name: /Move by/ }));
    const c = calls.find((x) => x.url.endsWith("/api/focusers/f-1/move"))!;
    expect(JSON.parse(String(c.init.body))).toEqual({ offset: 50 });
  });
});
```

Run:

```bash
cd web && npm test -- --run CameraView FilterWheelView FocuserView
```

Expected: all PASS.

- [ ] **Step 9.5: Format and commit**

```bash
cd web && npm run format
cd ..
git add web/src/views/CameraView.tsx web/src/views/CameraView.test.tsx \
        web/src/views/FilterWheelView.tsx web/src/views/FilterWheelView.test.tsx \
        web/src/views/FocuserView.tsx web/src/views/FocuserView.test.tsx
git commit -m "feat(web): camera, filter wheel, focuser control panels"
```

---

### Task 10: Sequence editor + runner with live progress

**Files:**
- Create: `web/src/api/endpoints/sequences.ts`
- Create: `web/src/ui/ProgressBar.tsx`
- Modify: `web/src/views/SequenceEditorView.tsx`
- Modify: `web/src/views/SequenceRunnerView.tsx`
- Test: `web/src/views/SequenceEditorView.test.tsx`
- Test: `web/src/views/SequenceRunnerView.test.tsx`

- [ ] **Step 10.1: Create `web/src/api/endpoints/sequences.ts`**

```typescript
import { apiFetch } from "../client";
import type { SequenceDefinitionDto, SequenceView } from "../types";

export interface SequenceListFilters {
  session_id?: number;
  limit?: number;
  offset?: number;
}

function qs(o: Record<string, unknown>): string {
  const p = new URLSearchParams();
  Object.entries(o).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  });
  const s = p.toString();
  return s ? `?${s}` : "";
}

export const sequencesApi = {
  list: (f: SequenceListFilters = {}) => apiFetch<SequenceView[]>(`/api/sequences${qs(f)}`),
  get: (id: number) => apiFetch<SequenceView>(`/api/sequences/${id}`),
  submit: (def: SequenceDefinitionDto) =>
    apiFetch<SequenceView>("/api/sequences", { method: "POST", body: def }),
  pause: (id: number) =>
    apiFetch<{ status: string }>(`/api/sequences/${id}/pause`, { method: "POST" }),
  resume: (id: number) =>
    apiFetch<{ status: string }>(`/api/sequences/${id}/resume`, { method: "POST" }),
  abort: (id: number, reason?: string) =>
    apiFetch<{ status: string }>(`/api/sequences/${id}/abort`, {
      method: "POST",
      body: reason ? { reason } : {},
    }),
};
```

- [ ] **Step 10.2: Create `web/src/ui/ProgressBar.tsx`**

```tsx
export function ProgressBar({ value, total }: { value: number; total: number }) {
  const pct = total <= 0 ? 0 : Math.min(100, Math.max(0, Math.round((value / total) * 100)));
  return (
    <div
      role="progressbar"
      aria-valuenow={pct}
      aria-valuemin={0}
      aria-valuemax={100}
      style={{
        background: "var(--color-surface-2)",
        height: 10,
        borderRadius: 999,
        border: "1px solid var(--color-border)",
        overflow: "hidden",
      }}
    >
      <div style={{
        width: `${pct}%`,
        height: "100%",
        background: "var(--color-accent)",
        transition: "width 0.2s ease",
      }} />
    </div>
  );
}
```

- [ ] **Step 10.3: Replace `web/src/views/SequenceEditorView.tsx`**

```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { devicesApi } from "@/api/endpoints/devices";
import { sequencesApi } from "@/api/endpoints/sequences";
import { Card } from "@/ui/Card";
import type { PreStepDto, SequenceDefinitionDto, SequenceStepDto } from "@/api/types";

const EMPTY_STEP: SequenceStepDto = { filter: "L", exposure_s: 30, count: 5 };

export function SequenceEditorView() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const devices = useQuery({ queryKey: ["devices"], queryFn: devicesApi.list });
  const recent = useQuery({ queryKey: ["sequences", { limit: 20 }],
    queryFn: () => sequencesApi.list({ limit: 20 }) });

  const [name, setName] = useState("Quick run");
  const [targetId, setTargetId] = useState("");
  const [steps, setSteps] = useState<SequenceStepDto[]>([{ ...EMPTY_STEP }]);
  const [pre, setPre] = useState<PreStepDto[]>([]);
  const [dither, setDither] = useState({ enabled: false, pixels: 10, every_n_subs: 1 });
  const [mountId, setMountId] = useState("");
  const [cameraId, setCameraId] = useState("");
  const [filterWheelId, setFilterWheelId] = useState("");
  const [focuserId, setFocuserId] = useState("");

  const submit = useMutation({
    mutationFn: () => {
      const def: SequenceDefinitionDto = {
        name,
        target_id: targetId || undefined,
        dither,
        pre_steps: pre,
        steps,
        device_ids: {
          mount_id: mountId || undefined,
          camera_id: cameraId || undefined,
          filter_wheel_id: filterWheelId || undefined,
          focuser_id: focuserId || undefined,
        },
      };
      return sequencesApi.submit(def);
    },
    onSuccess: (run) => {
      qc.invalidateQueries({ queryKey: ["sequences", { limit: 20 }] });
      navigate(`/sequences/${run.id}`);
    },
  });

  const addStep = () => setSteps((s) => [...s, { ...EMPTY_STEP }]);
  const removeStep = (i: number) => setSteps((s) => s.filter((_, j) => j !== i));
  const setStep = (i: number, patch: Partial<SequenceStepDto>) =>
    setSteps((s) => s.map((x, j) => j === i ? { ...x, ...patch } : x));

  const togglePre = (t: PreStepDto["type"]) => setPre((arr) =>
    arr.find((p) => p.type === t) ? arr.filter((p) => p.type !== t) : [...arr, { type: t }]);

  const dev = (kind: string) => (devices.data ?? []).filter((d) => d.kind === kind);

  return (
    <div>
      <h1>Sequences</h1>

      <Card title="Editor" actions={
        <button disabled={submit.isPending || steps.length === 0} onClick={() => submit.mutate()}>
          Submit & start
        </button>
      }>
        <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: 8, marginBottom: 12 }}>
          <label style={{ display: "contents" }}><span>Name</span>
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label style={{ display: "contents" }}><span>Target ID</span>
            <input value={targetId} onChange={(e) => setTargetId(e.target.value)}
                   placeholder="messier:M31" />
          </label>
          <label style={{ display: "contents" }}><span>Mount</span>
            <select value={mountId} onChange={(e) => setMountId(e.target.value)}>
              <option value="">—</option>
              {dev("mount").map((d) => <option key={d.id} value={d.id}>{d.id}</option>)}
            </select>
          </label>
          <label style={{ display: "contents" }}><span>Camera</span>
            <select value={cameraId} onChange={(e) => setCameraId(e.target.value)}>
              <option value="">—</option>
              {dev("camera").map((d) => <option key={d.id} value={d.id}>{d.id}</option>)}
            </select>
          </label>
          <label style={{ display: "contents" }}><span>Filter wheel</span>
            <select value={filterWheelId} onChange={(e) => setFilterWheelId(e.target.value)}>
              <option value="">—</option>
              {dev("filterwheel").map((d) => <option key={d.id} value={d.id}>{d.id}</option>)}
            </select>
          </label>
          <label style={{ display: "contents" }}><span>Focuser</span>
            <select value={focuserId} onChange={(e) => setFocuserId(e.target.value)}>
              <option value="">—</option>
              {dev("focuser").map((d) => <option key={d.id} value={d.id}>{d.id}</option>)}
            </select>
          </label>
        </div>

        <h3>Pre-steps</h3>
        <label><input type="checkbox"
                      checked={!!pre.find((p) => p.type === "slew_and_sync")}
                      onChange={() => togglePre("slew_and_sync")} />
          {" "}Slew + plate-solve + sync</label><br/>
        <label><input type="checkbox"
                      checked={!!pre.find((p) => p.type === "autofocus")}
                      onChange={() => togglePre("autofocus")} />
          {" "}Autofocus</label>

        <h3>Steps</h3>
        <table>
          <thead><tr><th>Filter</th><th>Exposure (s)</th><th>Count</th><th>Name</th><th></th></tr></thead>
          <tbody>
            {steps.map((s, i) => (
              <tr key={i}>
                <td><input value={s.filter} onChange={(e) => setStep(i, { filter: e.target.value })} /></td>
                <td><input type="number" step="0.1" value={s.exposure_s}
                           onChange={(e) => setStep(i, { exposure_s: Number(e.target.value) })} /></td>
                <td><input type="number" min={1} value={s.count}
                           onChange={(e) => setStep(i, { count: Number(e.target.value) })} /></td>
                <td><input value={s.name ?? ""} onChange={(e) => setStep(i, { name: e.target.value })} /></td>
                <td><button onClick={() => removeStep(i)}>Remove</button></td>
              </tr>
            ))}
          </tbody>
        </table>
        <p><button onClick={addStep}>Add step</button></p>

        <h3>Dither</h3>
        <label><input type="checkbox" checked={dither.enabled}
                      onChange={(e) => setDither({ ...dither, enabled: e.target.checked })} />
          {" "}Enable</label>{" "}
        <label>pixels: <input type="number" min={1} value={dither.pixels}
                              onChange={(e) => setDither({ ...dither, pixels: Number(e.target.value) })} /></label>{" "}
        <label>every N subs: <input type="number" min={1} value={dither.every_n_subs}
                                    onChange={(e) => setDither({ ...dither, every_n_subs: Number(e.target.value) })} /></label>

        {submit.error && <p style={{ color: "var(--color-danger)" }}>{(submit.error as Error).message}</p>}
      </Card>

      <Card title="Recent sequences">
        {recent.data?.length === 0 && <p>No sequences yet.</p>}
        {recent.data && (
          <table>
            <thead><tr><th>ID</th><th>Name</th><th>Status</th><th>Subs</th><th></th></tr></thead>
            <tbody>
              {recent.data.map((s) => (
                <tr key={s.id}>
                  <td>#{s.id}</td>
                  <td>{s.name}</td>
                  <td><code>{s.status}</code></td>
                  <td>{s.subs_completed}/{s.subs_total}</td>
                  <td><a href={`/sequences/${s.id}`}>open</a></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
```

- [ ] **Step 10.4: Replace `web/src/views/SequenceRunnerView.tsx`**

```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { useParams } from "react-router-dom";
import { sequencesApi } from "@/api/endpoints/sequences";
import { Card } from "@/ui/Card";
import { ConfirmButton } from "@/ui/ConfirmButton";
import { ProgressBar } from "@/ui/ProgressBar";
import { useEventStream } from "@/events/EventStream";

export function SequenceRunnerView() {
  const { id } = useParams<{ id: string }>();
  const runId = Number(id);
  const qc = useQueryClient();
  const { subscribe } = useEventStream();
  const run = useQuery({
    queryKey: ["sequence", runId],
    queryFn: () => sequencesApi.get(runId),
    refetchInterval: 5_000,
  });

  useEffect(() => {
    return subscribe("sequence", (e) => {
      const target = e.payload && (e.payload as Record<string, unknown>)["run_id"];
      if (typeof target === "number" && target === runId) {
        qc.invalidateQueries({ queryKey: ["sequence", runId] });
      }
    });
  }, [subscribe, qc, runId]);

  const pause = useMutation({ mutationFn: () => sequencesApi.pause(runId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sequence", runId] }) });
  const resume = useMutation({ mutationFn: () => sequencesApi.resume(runId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sequence", runId] }) });
  const abort = useMutation({ mutationFn: () => sequencesApi.abort(runId, "user"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sequence", runId] }) });

  if (run.isLoading) return <p>Loading…</p>;
  if (run.error) return <p style={{ color: "var(--color-danger)" }}>{(run.error as Error).message}</p>;
  if (!run.data) return <p>Not found.</p>;
  const r = run.data;

  return (
    <div>
      <h1>Sequence #{r.id} — {r.name}</h1>
      <Card title="Status">
        <p><code>{r.status}</code> {r.failure_reason && <>· {r.failure_reason}</>}</p>
        <ProgressBar value={r.subs_completed} total={r.subs_total} />
        <p>{r.subs_completed} / {r.subs_total} subs
          {r.current_step_index != null && <> · step {r.current_step_index + 1}</>}
          {r.current_sub_index != null && <> · sub {r.current_sub_index + 1}</>}
        </p>
        <p>
          <button disabled={r.status !== "RUNNING" || pause.isPending} onClick={() => pause.mutate()}>Pause</button>{" "}
          <button disabled={r.status !== "PAUSED" || resume.isPending} onClick={() => resume.mutate()}>Resume</button>{" "}
          <ConfirmButton label="Abort" confirmLabel="Confirm abort"
                         onConfirm={() => abort.mutate()} danger />
        </p>
      </Card>

      {r.definition && (
        <Card title="Definition">
          <pre style={{ background: "var(--color-surface)", padding: 8, overflow: "auto" }}>
{JSON.stringify(r.definition, null, 2)}
          </pre>
        </Card>
      )}
    </div>
  );
}
```

- [ ] **Step 10.5: Tests**

`web/src/views/SequenceEditorView.test.tsx`:

```tsx
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "@/test/render";
import { SequenceEditorView } from "./SequenceEditorView";
import { installFetchMock, uninstallFetchMock } from "@/test/mocks";
import { clearToken, setToken } from "@/api/token";

describe("SequenceEditorView", () => {
  beforeEach(() => { clearToken(); setToken("dev"); });
  afterEach(() => { uninstallFetchMock(); clearToken(); });

  it("submits a sequence and navigates to the runner", async () => {
    const { calls } = installFetchMock([
      { match: "/api/devices", respond: { body: [
        { id: "mount-1", indiName: "M", kind: "mount", state: "IDLE", connected: true },
        { id: "cam-1", indiName: "C", kind: "camera", state: "READY", connected: true },
      ]}},
      { match: /\/api\/sequences\?/, respond: { body: [] } },
      { match: "/api/sequences", respond: (url, init) => {
        if (init.method === "POST") {
          return { body: { id: 9, session_id: null, name: "Quick run", status: "PENDING",
            failure_reason: null, created_at: "2026", started_at: null, finished_at: null,
            current_step_index: null, current_sub_index: null,
            subs_completed: 0, subs_total: 5, definition: null } };
        }
        return { body: [] };
      } },
    ]);
    renderWithProviders(<SequenceEditorView />);
    await screen.findByRole("button", { name: /Submit & start/i });
    await userEvent.click(screen.getByRole("button", { name: /Submit & start/i }));
    expect(calls.some((c) => c.url === "/api/sequences" && c.init.method === "POST")).toBe(true);
  });
});
```

`web/src/views/SequenceRunnerView.test.tsx`:

```tsx
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import { Routes, Route } from "react-router-dom";
import { renderWithProviders } from "@/test/render";
import { SequenceRunnerView } from "./SequenceRunnerView";
import { installFetchMock, uninstallFetchMock } from "@/test/mocks";
import { clearToken, setToken } from "@/api/token";

describe("SequenceRunnerView", () => {
  beforeEach(() => { clearToken(); setToken("dev"); });
  afterEach(() => { uninstallFetchMock(); clearToken(); });

  it("renders status and progress for an existing sequence", async () => {
    installFetchMock([
      { match: "/api/sequences/42", respond: { body: {
        id: 42, session_id: null, name: "Demo", status: "RUNNING",
        failure_reason: null, created_at: "2026", started_at: "2026", finished_at: null,
        current_step_index: 0, current_sub_index: 1,
        subs_completed: 1, subs_total: 5,
        definition: null,
      } } },
    ]);
    renderWithProviders(
      <Routes>
        <Route path="/sequences/:id" element={<SequenceRunnerView />} />
      </Routes>,
      { route: "/sequences/42" },
    );
    expect(await screen.findByText(/Demo/)).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "20");
  });
});
```

Run:

```bash
cd web && npm test -- --run SequenceEditorView SequenceRunnerView
```

Expected: PASS.

- [ ] **Step 10.6: Format and commit**

```bash
cd web && npm run format
cd ..
git add web/src/api/endpoints/sequences.ts web/src/ui/ProgressBar.tsx \
        web/src/views/SequenceEditorView.tsx web/src/views/SequenceEditorView.test.tsx \
        web/src/views/SequenceRunnerView.tsx web/src/views/SequenceRunnerView.test.tsx
git commit -m "feat(web): sequence editor and live runner view"
```

---

### Task 11: Image gallery (thumbnails, FITS download, delete)

**Files:**
- Modify: `web/src/api/endpoints/images.ts` (extend stub from Task 8)
- Modify: `web/src/views/GalleryView.tsx`
- Test: `web/src/views/GalleryView.test.tsx`

- [ ] **Step 11.1: Extend `web/src/api/endpoints/images.ts`**

Add `get`, `delete`, and `downloadFits` (auth-aware blob fetch) below the existing `list`:

```typescript
import { apiBlob, apiFetch } from "../client";
import type { ImageView } from "../types";

export interface ImageListFilters {
  device?: string;
  session_id?: number;
  target?: string;
  filter?: string;
  limit?: number;
  offset?: number;
}

function qs(filters: ImageListFilters): string {
  const p = new URLSearchParams();
  Object.entries(filters).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  });
  const s = p.toString();
  return s ? `?${s}` : "";
}

export const imagesApi = {
  list: (filters: ImageListFilters = {}) => apiFetch<ImageView[]>(`/api/images${qs(filters)}`),
  get: (id: number) => apiFetch<ImageView>(`/api/images/${id}`),
  delete: (id: number) => apiFetch<void>(`/api/images/${id}`, { method: "DELETE" }),
  downloadFits: async (id: number, filename: string) => {
    const blob = await apiBlob(`/api/images/${id}.fits`);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },
};
```

- [ ] **Step 11.2: Replace `web/src/views/GalleryView.tsx`**

```tsx
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { imagesApi, type ImageListFilters } from "@/api/endpoints/images";
import { Card } from "@/ui/Card";
import { useEventStream } from "@/events/EventStream";
import { getToken } from "@/api/token";

export function GalleryView() {
  const qc = useQueryClient();
  const { subscribe } = useEventStream();
  const [filters, setFilters] = useState<ImageListFilters>({ limit: 100, offset: 0 });

  const list = useQuery({
    queryKey: ["images", filters],
    queryFn: () => imagesApi.list(filters),
  });

  const remove = useMutation({
    mutationFn: (id: number) => imagesApi.delete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["images"] }),
  });

  // SSE invalidation: a new image arrival on the camera topic should refresh the gallery.
  useEffect(
    () => subscribe("camera", () => qc.invalidateQueries({ queryKey: ["images"] })),
    [subscribe, qc],
  );

  const token = getToken();

  return (
    <div>
      <h1>Gallery</h1>
      <Card title="Filters">
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <label>Device <input value={filters.device ?? ""}
            onChange={(e) => setFilters((f) => ({ ...f, device: e.target.value }))} /></label>
          <label>Target <input value={filters.target ?? ""}
            onChange={(e) => setFilters((f) => ({ ...f, target: e.target.value }))} /></label>
          <label>Filter <input value={filters.filter ?? ""}
            onChange={(e) => setFilters((f) => ({ ...f, filter: e.target.value }))} /></label>
          <button onClick={() => qc.invalidateQueries({ queryKey: ["images"] })}>Refresh</button>
        </div>
      </Card>

      <Card title={`Images (${list.data?.length ?? 0})`}>
        {list.isLoading && <p>Loading…</p>}
        {list.data?.length === 0 && <p>No images yet.</p>}
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
          gap: 12,
        }}>
          {(list.data ?? []).map((img) => (
            <article key={img.id} style={{
              background: "var(--color-surface)", border: "1px solid var(--color-border)",
              borderRadius: 6, padding: 8,
            }}>
              {/* Thumbnails are public from a UI perspective but still require the bearer.
                  We embed via a <img> tag with a query-string token; backend accepts that
                  alternate auth path (added in Task 14). */}
              <img
                src={`/api/images/${img.id}/thumb.jpg?token=${encodeURIComponent(token ?? "")}`}
                alt={`#${img.id}`}
                style={{ width: "100%", height: 160, objectFit: "cover", background: "#000" }}
                loading="lazy"
              />
              <div style={{ fontSize: 12, marginTop: 6 }}>
                #{img.id} · {img.target} · {img.filter} · {img.exposureSec}s
                <br/>
                <code>{img.device}</code> · seq {img.seq}
              </div>
              <div style={{ marginTop: 6, display: "flex", gap: 6 }}>
                <button onClick={() => imagesApi.downloadFits(img.id, `image-${img.id}.fits`)}>
                  FITS
                </button>
                <button onClick={() => remove.mutate(img.id)}>Delete</button>
              </div>
            </article>
          ))}
        </div>
      </Card>
    </div>
  );
}
```

- [ ] **Step 11.3: Create `web/src/views/GalleryView.test.tsx`**

```tsx
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "@/test/render";
import { GalleryView } from "./GalleryView";
import { installFetchMock, uninstallFetchMock } from "@/test/mocks";
import { clearToken, setToken } from "@/api/token";

describe("GalleryView", () => {
  beforeEach(() => { clearToken(); setToken("dev"); });
  afterEach(() => { uninstallFetchMock(); clearToken(); });

  it("renders thumbnails and triggers a delete", async () => {
    const { calls } = installFetchMock([
      { match: /\/api\/images(\?.*)?$/, respond: { body: [{
        id: 1, sessionId: null, device: "cam-1", filter: "L", target: "M31",
        exposureSec: 5, step: "L", seq: 0, fitsPath: "/p", thumbPath: "/t",
        bytes: 100, width: 1, height: 1, bitpix: 16, dateObs: null, createdAt: "2026",
      }]}},
      { match: /\/api\/images\/1$/, respond: { status: 204 } },
    ]);
    renderWithProviders(<GalleryView />);
    expect(await screen.findByAltText("#1")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Delete/ }));
    expect(calls.some((c) => c.url.endsWith("/api/images/1") && c.init.method === "DELETE")).toBe(true);
  });
});
```

Run:

```bash
cd web && npm test -- --run GalleryView
```

Expected: PASS.

- [ ] **Step 11.4: Format and commit**

```bash
cd web && npm run format
cd ..
git add web/src/api/endpoints/images.ts web/src/views/GalleryView.tsx \
        web/src/views/GalleryView.test.tsx
git commit -m "feat(web): image gallery with thumbnails, FITS download, delete"
```

---

### Task 12: Session history view

**Files:**
- Create: `web/src/api/endpoints/sessions.ts`
- Modify: `web/src/views/SessionsView.tsx`
- Test: `web/src/views/SessionsView.test.tsx`

- [ ] **Step 12.1: Create `web/src/api/endpoints/sessions.ts`**

```typescript
import { apiFetch } from "../client";
import type { SessionDetail, SessionRow } from "../types";

export const sessionsApi = {
  list: () => apiFetch<SessionRow[]>("/api/sessions"),
  get: (id: number) => apiFetch<SessionDetail>(`/api/sessions/${id}`),
  open: (name: string) =>
    apiFetch<SessionRow>("/api/sessions", { method: "POST", body: { name } }),
  close: (id: number) =>
    apiFetch<{ status: string }>(`/api/sessions/${id}/close`, { method: "POST" }),
};
```

- [ ] **Step 12.2: Replace `web/src/views/SessionsView.tsx`**

```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { sessionsApi } from "@/api/endpoints/sessions";
import { Card } from "@/ui/Card";

export function SessionsView() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const params = useParams<{ id?: string }>();
  const sessionId = params.id ? Number(params.id) : null;

  const list = useQuery({ queryKey: ["sessions"], queryFn: sessionsApi.list });
  const detail = useQuery({
    queryKey: ["session", sessionId],
    queryFn: () => sessionsApi.get(sessionId!),
    enabled: sessionId !== null,
  });
  const [name, setName] = useState("");
  const open = useMutation({
    mutationFn: () => sessionsApi.open(name || "session"),
    onSuccess: (s) => { qc.invalidateQueries({ queryKey: ["sessions"] }); navigate(`/sessions/${s.id}`); },
  });
  const close = useMutation({
    mutationFn: (id: number) => sessionsApi.close(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sessions"] }),
  });

  return (
    <div>
      <h1>Sessions</h1>

      <Card title="Open new session">
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="name" />{" "}
        <button onClick={() => open.mutate()}>Open</button>
      </Card>

      <Card title="All sessions">
        {list.isLoading && <p>Loading…</p>}
        {list.data && (
          <table>
            <thead><tr><th>ID</th><th>Name</th><th>Opened</th><th>Closed</th><th></th></tr></thead>
            <tbody>
              {list.data.map((s) => (
                <tr key={s.id}>
                  <td>#{s.id}</td>
                  <td>{s.name}</td>
                  <td>{s.opened_at}</td>
                  <td>{s.closed_at ?? "—"}</td>
                  <td>
                    <button onClick={() => navigate(`/sessions/${s.id}`)}>open</button>{" "}
                    {!s.closed_at && <button onClick={() => close.mutate(s.id)}>close</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {sessionId !== null && detail.data && (
        <Card title={`Events for #${sessionId}`}>
          <table>
            <thead><tr><th>ID</th><th>ts</th><th>Topic</th><th>Type</th><th>Payload</th></tr></thead>
            <tbody>
              {detail.data.events.map((e) => (
                <tr key={e.id}>
                  <td>#{e.id}</td>
                  <td>{e.ts}</td>
                  <td><code>{e.topic}</code></td>
                  <td>{e.type}</td>
                  <td><code style={{ whiteSpace: "pre-wrap" }}>{e.payload_json ?? ""}</code></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
```

- [ ] **Step 12.3: Create `web/src/views/SessionsView.test.tsx`**

```tsx
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import { Routes, Route } from "react-router-dom";
import { renderWithProviders } from "@/test/render";
import { SessionsView } from "./SessionsView";
import { installFetchMock, uninstallFetchMock } from "@/test/mocks";
import { clearToken, setToken } from "@/api/token";

describe("SessionsView", () => {
  beforeEach(() => { clearToken(); setToken("dev"); });
  afterEach(() => { uninstallFetchMock(); clearToken(); });

  it("lists sessions and shows event detail when an id is in the route", async () => {
    installFetchMock([
      { match: /\/api\/sessions$/, respond: { body: [
        { id: 1, name: "first", opened_at: "2026-04-23T00:00:00Z", closed_at: null },
      ]}},
      { match: /\/api\/sessions\/1$/, respond: { body: {
        session: { id: 1, name: "first", opened_at: "2026", closed_at: null },
        events: [{ id: 100, ts: "2026", topic: "system", type: "boot", payload_json: "{}" }],
      }}},
    ]);
    renderWithProviders(
      <Routes>
        <Route path="/sessions/:id" element={<SessionsView />} />
        <Route path="/sessions" element={<SessionsView />} />
      </Routes>,
      { route: "/sessions/1" },
    );
    expect(await screen.findByText("first")).toBeInTheDocument();
    expect(await screen.findByText("boot")).toBeInTheDocument();
  });
});
```

Run:

```bash
cd web && npm test -- --run SessionsView
```

Expected: PASS.

- [ ] **Step 12.4: Format and commit**

```bash
cd web && npm run format
cd ..
git add web/src/api/endpoints/sessions.ts web/src/views/SessionsView.tsx \
        web/src/views/SessionsView.test.tsx
git commit -m "feat(web): session history list and detail"
```

---

### Task 13: Safety panel — rules, e-stop, latched state, sensor reading, active target

**Files:**
- Create: `web/src/api/endpoints/safety.ts`
- Modify: `web/src/views/SafetyView.tsx`
- Modify: `web/src/ui/Layout.tsx` to surface a global e-stop banner
- Test: `web/src/views/SafetyView.test.tsx`

- [ ] **Step 13.1: Create `web/src/api/endpoints/safety.ts`**

```typescript
import { apiFetch } from "../client";
import type { SafetyStatusView } from "../types";

export interface SensorReadingBody {
  sensor: string;
  ts?: string;
  values: Record<string, number | string | boolean>;
}

export interface ActiveTargetBody {
  targetId: string;
  raJ2000Deg: number;
  decJ2000Deg: number;
}

export const safetyApi = {
  status: () => apiFetch<SafetyStatusView>("/api/safety/rules"),
  reload: () => apiFetch<{ rules: number }>("/api/safety/rules/reload", { method: "POST" }),
  eStop: (reason?: string) =>
    apiFetch<{ status: string }>("/api/safety/e-stop", {
      method: "POST", body: reason ? { reason } : {},
    }),
  reset: () => apiFetch<{ status: string }>("/api/safety/reset", { method: "POST" }),
  postReading: (body: SensorReadingBody) =>
    apiFetch<{ status: string }>("/api/safety/sensors/readings", { method: "POST", body }),
  setActiveTarget: (body: ActiveTargetBody) =>
    apiFetch<{ status: string }>("/api/safety/active-target", { method: "POST", body }),
};
```

- [ ] **Step 13.2: Replace `web/src/views/SafetyView.tsx`**

```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { safetyApi } from "@/api/endpoints/safety";
import { Banner } from "@/ui/Banner";
import { Card } from "@/ui/Card";
import { ConfirmButton } from "@/ui/ConfirmButton";
import { useEventStream } from "@/events/EventStream";

export function SafetyView() {
  const qc = useQueryClient();
  const status = useQuery({ queryKey: ["safety"], queryFn: safetyApi.status });
  const { subscribe } = useEventStream();
  useEffect(() => subscribe("safety", () =>
    qc.invalidateQueries({ queryKey: ["safety"] })), [subscribe, qc]);

  const reload = useMutation({ mutationFn: () => safetyApi.reload(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["safety"] }) });
  const eStop = useMutation({ mutationFn: (reason: string) => safetyApi.eStop(reason),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["safety"] }) });
  const reset = useMutation({ mutationFn: () => safetyApi.reset(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["safety"] }) });

  const [reason, setReason] = useState("manual");
  const [sensor, setSensor] = useState("rain");
  const [values, setValues] = useState('{"rain": true}');
  const postReading = useMutation({
    mutationFn: () => {
      let parsed: Record<string, number | string | boolean>;
      try { parsed = JSON.parse(values); }
      catch { throw new Error("values must be JSON object"); }
      return safetyApi.postReading({ sensor, values: parsed });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["safety"] }),
  });

  const [target, setTarget] = useState({ targetId: "", ra: "0", dec: "0" });
  const setActive = useMutation({
    mutationFn: () => safetyApi.setActiveTarget({
      targetId: target.targetId,
      raJ2000Deg: Number(target.ra),
      decJ2000Deg: Number(target.dec),
    }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["safety"] }),
  });

  return (
    <div>
      <h1>Safety</h1>
      {status.data && status.data.latched.length > 0 && (
        <Banner kind="danger" action={
          <button onClick={() => reset.mutate()}>Reset</button>
        }>
          <strong>Latched:</strong> {status.data.latched.join(", ")}
        </Banner>
      )}

      <Card title="Loaded rules" actions={
        <button onClick={() => reload.mutate()}>Reload safety.yaml</button>
      }>
        {status.isLoading && <p>Loading…</p>}
        {status.data && (
          <table>
            <thead><tr><th>Name</th><th>When</th><th>Action</th><th>Latched</th></tr></thead>
            <tbody>
              {status.data.rules.map((r) => (
                <tr key={r.name}>
                  <td>{r.name}</td>
                  <td><code>{JSON.stringify(r.when)}</code></td>
                  <td><code>{r.action}</code></td>
                  <td>{r.latched ? "yes" : ""}</td>
                </tr>
              ))}
              {status.data.rules.length === 0 && (
                <tr><td colSpan={4} style={{ color: "var(--color-text-muted)" }}>
                  No rules loaded.
                </td></tr>
              )}
            </tbody>
          </table>
        )}
      </Card>

      <Card title="Emergency stop">
        <p>Aborts the running exposure, stops the sequence, parks the mount, halts cooling.</p>
        <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="reason" />{" "}
        <ConfirmButton label="E-STOP" confirmLabel="Confirm E-STOP"
                       danger onConfirm={() => eStop.mutate(reason)} />
        {eStop.error && <p style={{ color: "var(--color-danger)" }}>{(eStop.error as Error).message}</p>}
      </Card>

      <Card title="Post test sensor reading">
        <label>Sensor <input value={sensor} onChange={(e) => setSensor(e.target.value)} /></label>{" "}
        <label>Values (JSON)
          <input style={{ width: 320 }} value={values}
                 onChange={(e) => setValues(e.target.value)} />
        </label>{" "}
        <button onClick={() => postReading.mutate()}>Submit</button>
        {postReading.error && (
          <p style={{ color: "var(--color-danger)" }}>{(postReading.error as Error).message}</p>
        )}
      </Card>

      <Card title="Active target (drives altitude rules)">
        <label>Target ID <input value={target.targetId}
          onChange={(e) => setTarget({ ...target, targetId: e.target.value })} /></label>{" "}
        <label>RA (°) <input type="number" value={target.ra}
          onChange={(e) => setTarget({ ...target, ra: e.target.value })} /></label>{" "}
        <label>Dec (°) <input type="number" value={target.dec}
          onChange={(e) => setTarget({ ...target, dec: e.target.value })} /></label>{" "}
        <button disabled={!target.targetId} onClick={() => setActive.mutate()}>Set active</button>
        {status.data?.activeTargetId && (
          <p>Current active target: <code>{status.data.activeTargetId}</code></p>
        )}
      </Card>
    </div>
  );
}
```

- [ ] **Step 13.3: Modify `web/src/ui/Layout.tsx` to show a global e-stop banner**

Replace its body:

```tsx
import { Outlet, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { NavBar } from "./NavBar";
import { ErrorBoundary } from "./ErrorBoundary";
import { Banner } from "./Banner";
import { safetyApi } from "@/api/endpoints/safety";
import { useEventStream } from "@/events/EventStream";
import { useQueryClient } from "@tanstack/react-query";

export function Layout() {
  const qc = useQueryClient();
  const { subscribe } = useEventStream();
  const safety = useQuery({
    queryKey: ["safety"], queryFn: safetyApi.status,
    refetchInterval: 30_000,
  });
  useEffect(() => subscribe("safety", () =>
    qc.invalidateQueries({ queryKey: ["safety"] })), [subscribe, qc]);

  return (
    <>
      <NavBar />
      <main style={{ padding: 24, maxWidth: 1200, margin: "0 auto" }}>
        {safety.data && safety.data.latched.length > 0 && (
          <Banner kind="danger" action={<Link to="/safety"><button>Open Safety</button></Link>}>
            <strong>Safety latched:</strong> {safety.data.latched.join(", ")}
          </Banner>
        )}
        <ErrorBoundary>
          <Outlet />
        </ErrorBoundary>
      </main>
    </>
  );
}
```

- [ ] **Step 13.4: Create `web/src/views/SafetyView.test.tsx`**

```tsx
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "@/test/render";
import { SafetyView } from "./SafetyView";
import { installFetchMock, uninstallFetchMock } from "@/test/mocks";
import { clearToken, setToken } from "@/api/token";

describe("SafetyView", () => {
  beforeEach(() => { clearToken(); setToken("dev"); });
  afterEach(() => { uninstallFetchMock(); clearToken(); });

  it("requires confirmation before e-stop and surfaces latched rules", async () => {
    const { calls } = installFetchMock([
      { match: "/api/safety/rules", respond: { body: {
        rules: [{ name: "rain", action: "e_stop", when: { rain_detected: true }, latched: true }],
        latched: ["rain"],
        activeTargetId: null,
      }}},
      { match: "/api/safety/e-stop", respond: { body: { status: "ok" } } },
    ]);
    renderWithProviders(<SafetyView />);
    expect(await screen.findByText(/Latched:/)).toBeInTheDocument();
    const btn = screen.getByRole("button", { name: /^E-STOP$/ });
    await userEvent.click(btn);
    await userEvent.click(await screen.findByRole("button", { name: /Confirm E-STOP/ }));
    expect(calls.some((c) => c.url.endsWith("/api/safety/e-stop"))).toBe(true);
  });
});
```

Run:

```bash
cd web && npm test -- --run SafetyView
```

Expected: PASS.

- [ ] **Step 13.5: Format and commit**

```bash
cd web && npm run format
cd ..
git add web/src/api/endpoints/safety.ts web/src/views/SafetyView.tsx \
        web/src/views/SafetyView.test.tsx web/src/ui/Layout.tsx
git commit -m "feat(web): safety panel and global latched-rules banner"
```

---

### Task 14: SPA fallback, classpath bundling, and integration test

**Files:**
- Create: `src/main/java/dev/nocs/web/WebSpaController.java`
- Create: `src/main/java/dev/nocs/web/WebSpaConfig.java`
- Modify: `src/main/java/dev/nocs/security/BearerTokenFilter.java`
- Modify: `src/main/java/dev/nocs/security/SecurityConfig.java`
- Test: `src/test/java/dev/nocs/web/WebSpaControllerTest.java`

- [ ] **Step 14.1: Create `src/main/java/dev/nocs/web/WebSpaController.java`**

```java
package dev.nocs.web;

import jakarta.servlet.http.HttpServletRequest;
import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;

/**
 * Forwards GETs that don't match a REST mapping or a static asset to /index.html so that React Router
 * deep-links (e.g. /sequences/42) work from a fresh browser load.
 *
 * <p>This is mapped only to extension-less paths under /, so /api/** and /assets/**.* are not affected.
 */
@Controller
public class WebSpaController {

    @GetMapping(value = {
        "/dashboard", "/targets", "/mount", "/plate-solve",
        "/camera", "/filter-wheel", "/focuser",
        "/sequences", "/sequences/{id:[0-9]+}",
        "/gallery", "/sessions", "/sessions/{id:[0-9]+}",
        "/safety", "/settings"
    })
    public String spa() {
        return "forward:/index.html";
    }

    @RequestMapping(value = "/error", produces = "text/html")
    public String spaError(HttpServletRequest req) {
        Object status = req.getAttribute("jakarta.servlet.error.status_code");
        if (status != null && (Integer) status == 404
                && !String.valueOf(req.getAttribute("jakarta.servlet.error.request_uri")).startsWith("/api/")) {
            return "forward:/index.html";
        }
        return "forward:/static/error.html";
    }
}
```

- [ ] **Step 14.2: Create `src/main/java/dev/nocs/web/WebSpaConfig.java`**

```java
package dev.nocs.web;

import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.ResourceHandlerRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

@Configuration
public class WebSpaConfig implements WebMvcConfigurer {

    @Override
    public void addResourceHandlers(ResourceHandlerRegistry registry) {
        registry.addResourceHandler("/assets/**")
            .addResourceLocations("classpath:/static/assets/");
        registry.addResourceHandler("/favicon.svg", "/favicon.ico", "/index.html")
            .addResourceLocations("classpath:/static/");
    }
}
```

- [ ] **Step 14.3: Modify `src/main/java/dev/nocs/security/BearerTokenFilter.java`**

Add a query-string fallback so `EventSource` connections can authenticate (it cannot set custom headers) and so `<img>` tag thumbnail loads work without a custom header.

Replace the existing `doFilterInternal` body with:

```java
    @Override
    protected void doFilterInternal(HttpServletRequest req, HttpServletResponse res, FilterChain chain)
            throws ServletException, IOException {
        String token = extractToken(req);
        if (token != null && expectedToken != null && !expectedToken.isBlank() && expectedToken.equals(token)) {
            var auth = new UsernamePasswordAuthenticationToken(
                    "nocs-user",
                    null,
                    List.of(new SimpleGrantedAuthority("ROLE_USER")));
            SecurityContextHolder.getContext().setAuthentication(auth);
        }
        chain.doFilter(req, res);
    }

    private static String extractToken(HttpServletRequest req) {
        String header = req.getHeader("Authorization");
        if (header != null && header.startsWith("Bearer ")) {
            return header.substring("Bearer ".length()).trim();
        }
        // Fallback: ?token=... — only honoured for GET /api/events and GET /api/images/**.
        String path = req.getRequestURI();
        if ("GET".equalsIgnoreCase(req.getMethod())
                && (path.equals("/api/events")
                    || path.startsWith("/api/images/"))) {
            String t = req.getParameter("token");
            if (t != null && !t.isBlank()) return t;
        }
        return null;
    }
```

- [ ] **Step 14.4: Modify `src/main/java/dev/nocs/security/SecurityConfig.java`**

Add `/assets/**` and `/favicon.svg` to the permit-all list (both are part of the SPA shell):

```java
.authorizeHttpRequests(authz -> authz
        .requestMatchers("/", "/index.html", "/assets/**", "/static/**", "/favicon.ico", "/favicon.svg").permitAll()
        .requestMatchers("/api/**").authenticated()
        .anyRequest().permitAll())
```

- [ ] **Step 14.5: Create `src/test/java/dev/nocs/web/WebSpaControllerTest.java`**

```java
package dev.nocs.web;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.forwardedUrl;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;

@SpringBootTest
@AutoConfigureMockMvc
@TestPropertySource(properties = {
    "nocs.auth.token=test-token",
    "nocs.indi.mode=disabled",
})
class WebSpaControllerTest {

    @Autowired MockMvc mvc;

    @Test
    void spaRouteForwardsToIndex() throws Exception {
        mvc.perform(get("/sequences/42").header("Authorization", "Bearer test-token"))
           .andExpect(forwardedUrl("/index.html"));
    }

    @Test
    void rootServesIndexHtml() throws Exception {
        mvc.perform(get("/index.html"))
           .andExpect(status().isOk())
           .andExpect(content().contentTypeCompatibleWith("text/html"));
    }

    @Test
    void apiStillRequiresAuth() throws Exception {
        mvc.perform(get("/api/config"))
           .andExpect(status().isUnauthorized());
    }
}
```

- [ ] **Step 14.6: Run the full Java + web test suites**

```bash
./gradlew check
```

Expected:
- `npmCiWeb`, `npmBuildWeb` and `syncWebDist` run as part of `processResources`.
- `npmTestWeb`, `npmLintWeb`, `npmFormatCheckWeb` pass.
- `WebSpaControllerTest` passes.

If `WebSpaControllerTest.rootServesIndexHtml` fails because `index.html` has not been built yet, the `processResources` chain wired in Task 1 should have produced it. Re-run `./gradlew syncWebDist` and inspect `build/generated-resources/web/static/index.html`.

- [ ] **Step 14.7: Commit**

```bash
git add src/main/java/dev/nocs/web src/main/java/dev/nocs/security \
        src/test/java/dev/nocs/web
git commit -m "feat(web): SPA fallback, asset wiring, and event/image token query auth"
```

---

### Task 15: CI hooks, README, jlink size sanity check

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`
- Modify: `build.gradle.kts` (extend `verifyArchiveSize` to log web-bundle size)

- [ ] **Step 15.1: Modify `.github/workflows/ci.yml` to install Node and cache npm**

In the existing build job (the one that already runs `./gradlew check runtimeDist`), add a Node setup step **before** the Gradle invocation, and cache the web `node_modules` keyed on `package-lock.json`. The exact step name in the file may vary, so insert after the JDK setup step:

```yaml
      - uses: actions/setup-node@v4
        with:
          node-version: '22.12.0'
          cache: 'npm'
          cache-dependency-path: web/package-lock.json

      - name: Cache web node_modules
        uses: actions/cache@v4
        with:
          path: web/node_modules
          key: ${{ runner.os }}-webnm-${{ hashFiles('web/package-lock.json') }}
          restore-keys: |
            ${{ runner.os }}-webnm-
```

(No other changes are needed — `./gradlew check runtimeDist` will pull the web build in via `processResources`.)

- [ ] **Step 15.2: Extend `verifyArchiveSize` to log SPA contribution**

Append to the existing task body in `build.gradle.kts`:

```kotlin
        val webDir = file("build/generated-resources/web/static")
        if (webDir.exists()) {
            val webBytes = webDir.walkTopDown().filter { it.isFile }.sumOf { it.length() }
            val webMb = webBytes.toDouble() / (1024.0 * 1024.0)
            logger.lifecycle(String.format("%-50s %6.1f MB (web/dist)", "web bundle", webMb))
            if (webBytes > 8L * 1024 * 1024) {
                logger.warn(
                    "Web bundle exceeds 8 MB — investigate Vite build output (vite-bundle-visualizer)."
                )
            }
        }
```

- [ ] **Step 15.3: Update `README.md`**

Add a `Web client` section near the existing `Build` / `Run` instructions. Use the snippet below verbatim:

````markdown
## Web client

The React + Vite + TypeScript SPA lives in `web/` and is served by the Spring app from `classpath:/static/`.

### Dev loop

In one terminal, run the backend:

```bash
./gradlew bootRun
```

In another, start Vite with HMR:

```bash
cd web && npm run dev
```

Vite listens on `http://localhost:5173` and proxies `/api/*` (REST + SSE) to `http://localhost:8080`.
The bearer token is whatever was generated on first run; paste it into the login panel.

### Build

`./gradlew bootJar` (or `runtimeDist`) automatically runs:

1. `npmCiWeb` — `npm ci` in `web/`
2. `npmBuildWeb` — `vite build` → `web/dist/`
3. `syncWebDist` — copies `web/dist/` into `build/generated-resources/web/static/`

The result is bundled inside the Spring boot jar (and therefore inside the jlink archive).

### Tests / lint / format

`./gradlew check` runs:

- Java: JUnit + MockMvc
- Web: `npm run test`, `npm run lint`, `npm run format:check`
````

- [ ] **Step 15.4: Run the whole pipeline locally**

```bash
./gradlew clean check runtimeDist verifyArchiveSize
```

Expected: every task green; `verifyArchiveSize` reports both the archive size and the `web bundle` line. Archive must stay under the 150 MB envelope (spec §14.1).

- [ ] **Step 15.5: Smoke test the running server**

```bash
./gradlew bootRun &
GRADLE_PID=$!
sleep 10
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8080/index.html
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8080/sequences/1
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8080/api/config
kill $GRADLE_PID
wait $GRADLE_PID 2>/dev/null || true
```

Expected: `200 200 401` — the SPA index and a deep-link route both return 200; `/api/config` rejects an unauthenticated call.

- [ ] **Step 15.6: Commit**

```bash
git add .github/workflows/ci.yml README.md build.gradle.kts
git commit -m "ci(web): node setup, cache, README, and bundle size sanity check"
```

---

## Demoable end state

After Task 15:

- `./gradlew clean check runtimeDist` produces `build/distributions/nocs-<version>-linux-x86_64.tar.gz` containing the bundled SPA inside the boot jar.
- Unpacking the archive and running `bin/nocs` starts NOCS on `http://localhost:8080`.
- Visiting that URL in a browser shows the login panel, accepts the bearer token, and exposes:
  - Live device dashboard with connect/disconnect (drives INDI sim drivers when `nocs.indi.mode=managed`).
  - Target search (`M31`, `NGC 7000`, `Vega`, …) backed by the bundled catalogs.
  - Manual mount slew/sync/park, camera expose/cool, filter-wheel select, focuser move.
  - Sequence editor → submit → live runner page with progress bar updating from SSE.
  - Image gallery showing thumbnails as they arrive, with FITS download and delete.
  - Plate-solve panel that drives `POST /api/platesolving/solve` and shows ASTAP install status.
  - Safety panel with rules table, latched indicator, e-stop (with confirm), reset, test sensor reading, active target setter.
  - Session history with per-session event table.
  - Settings: `config_kv` editor + observatories CRUD + token sign-out.
- A simulated end-to-end run (Plan G's smoke test) drives the gallery and runner views without code changes.

---

## Self-review notes

- **Spec coverage:** Every view in §15 has its own task. SSE topics from §8.3 are subscribed by the relevant view (mount/camera/filterwheel/focuser/sequence/safety/session/device_connection/system/target/sensor/platesolving). Authentication uses bearer tokens from §7. Static-only deployment matches §14.1 (archive contains the SPA bundled in the boot jar; the `web/` runtime dir from the spec is dropped in favour of jar bundling — a deliberate simplification documented in Task 14).
- **No placeholders:** Every step has either complete code or a literal command and expected output. The only generated artefact is `package-lock.json`, which `npm install` writes on Task 1.
- **Type consistency:** TypeScript DTOs in `web/src/api/types.ts` mirror the backend shapes (`SequenceView`, `ImageView`, `DeviceView`, `SafetyStatusView`, `InstallStatusView`, `PlateSolutionView`, etc.). Wire keys use snake_case (e.g. `subs_completed`, `current_step_index`, `target_id`) matching the Java DTOs serialized by Jackson.
- **Auth fallback honesty:** `EventSource` and `<img>` thumbnail loads cannot send custom headers; Task 14 extends `BearerTokenFilter` to accept a query-string `?token=` parameter for GETs to `/api/events` and `/api/images/**` only — every other path still requires the header.
- **Granularity:** Each task ends with a runnable test + commit. Tasks 1, 14, and 15 are the integration backbones; Tasks 2–13 are independent and can be parallelised across subagents.
