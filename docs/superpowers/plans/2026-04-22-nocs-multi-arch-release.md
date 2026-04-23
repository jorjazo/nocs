# NOCS Multi-arch Packaging & Release Implementation Plan (Plan I)

> **See also:** [NOCS v0.1 plan decomposition (A–I)](./2026-04-22-v0.1-plan-decomposition.md) — full roadmap and dependencies.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the Plan A jlink build so a single `./gradlew runtimeAll` invocation produces three self-contained release archives — `nocs-<version>-linux-x86_64.tar.gz`, `nocs-<version>-linux-arm64.tar.gz`, `nocs-<version>-windows-x86_64.zip` — each with the appropriate launcher (`bin/nocs` for Linux, `bin\nocs.bat` for Windows) and a bundled JDK 25 for that platform; verify each archive against the spec §14.1 envelope (≤150 MB), smoke-test the linux-x86_64 and windows-x86_64 archives in CI, do a structural check of the linux-arm64 archive (and a QEMU smoke if available), and add a tag-driven GitHub release workflow that publishes all three archives plus a `SHA256SUMS.txt` to GitHub Releases.

**Architecture:** Re-use the existing `org.beryx.runtime` plugin, but switch from a single implicit host-platform build to its `targetPlatform("<name>", <jdk-archive-url>)` API. The plugin downloads the foreign JDK once per target into Gradle's user cache, then runs `jlink --target-platform` against it to produce per-target images at `build/image/nocs-<target>/`. Three custom Gradle tasks (`runtimeTarLinuxX64`, `runtimeTarLinuxArm64`, `runtimeZipWindowsX64`) wrap each image into the right archive format with the right launchers retained and the wrong ones stripped. CI gains a Linux job that builds all three archives + smoke-tests the linux-x86_64 one, a Windows job that smoke-tests the windows-x86_64 zip, and (optionally) a QEMU job for the linux-arm64 archive. A separate `release.yml` workflow triggered by `v*` tags re-builds the archives, computes SHA-256 sums, and uploads everything as a GitHub Release.

**Tech Stack:**
- JDK 25.0.2+10 (Temurin GA, Feb 2026) — pinned per-platform JDK archives
- `org.beryx.runtime` 2.0.1 (already on the classpath from Plan A)
- Gradle 9.1 Kotlin DSL (already on the classpath from Plan A)
- GitHub Actions: `ubuntu-latest`, `windows-latest`, optional `docker/setup-qemu-action@v3` for arm64 smoke
- `actions/upload-artifact@v4` and `softprops/action-gh-release@v2` for the release workflow
- PowerShell 5+ (preinstalled on `windows-latest`) for the Windows smoke test

## Scope

### In scope for Plan I

1. Multi-platform jlink configuration in `build.gradle.kts` using `targetPlatform("<name>", <url>)` for `linux-x86_64`, `linux-arm64`, and `windows-x86_64`.
2. Per-platform archive tasks producing one tar.gz per Linux target and one zip for Windows, with platform-appropriate launchers and file permissions.
3. A `runtimeAll` aggregate task plus a deprecated `runtimeTarGz` alias that keeps the existing CI invocation working until step 6 lands.
4. Polished Windows launcher: pre-existing `bin\nocs.bat` from `org.beryx.runtime` is verified, and a small wrapper template (or a post-process step) ensures `NOCS_DATA_DIR` defaults to `%APPDATA%\nocs` instead of being unset. Linux launcher's `NOCS_DATA_DIR` default already comes from `DataDirBootstrap` so it does not need launcher changes.
5. A reusable Bash smoke script that handles both `.tar.gz` and `.zip` archives (Linux smoke), and a PowerShell smoke script for Windows.
6. CI workflow updated: matrix or two-job structure that builds all three archives on Linux, smoke-tests linux-x86_64 inline, downloads the windows-x86_64 zip on a `windows-latest` runner and smoke-tests it with PowerShell, and uses QEMU to smoke-test the linux-arm64 archive (best-effort: skip if `qemu-aarch64-static` is unavailable).
7. New `verifyArchiveSize` Gradle task that fails if any of the three archives exceeds 150 MB; wired into `runtimeAll` and CI.
8. New `release.yml` workflow triggered by `v*` tags that builds all three archives, computes `SHA256SUMS.txt`, and publishes a draft GitHub Release.
9. `README.md` install snippets updated for arm64 and Windows, with a checksum-verification example.

### Explicitly out of scope for Plan I

- macOS archives (`darwin-x86_64`, `darwin-arm64`) — not in spec §14.1.
- `.deb` / `.rpm` / `.msi` system packages and `systemd` units — explicit non-goal in spec §14.1.
- Auto-update logic or a packaged installer.
- Cold-start measurement on a real Raspberry Pi — the spec envelope (cold start ≤15 s on RPi 4) is checked manually before tagging a release; CI cannot reproduce real RPi performance honestly.
- Code signing / notarisation of Windows or macOS binaries.
- Reproducible-build flags (e.g. SOURCE_DATE_EPOCH); we accept timestamps inside the archives for v0.1.

## File Structure

All paths are relative to the repo root (`/home/jorjazo/dev/nocs/nocs`). Each file has one responsibility; none should exceed ~150 lines.

**New / modified build files:**

- Modify: `build.gradle.kts` — replace the single-platform `runtime { ... }` block with multi-platform `targetPlatform(...)` declarations; replace `runtimeTarGz` with three per-platform archive tasks (`runtimeTarLinuxX64`, `runtimeTarLinuxArm64`, `runtimeZipWindowsX64`) plus `runtimeAll` aggregate, a `patchWindowsLauncher` post-process task that injects a `NOCS_DATA_DIR` default into the generated `bin/nocs.bat`, and a `verifyArchiveSize` envelope check.

**New scripts:**

- Create: `smoke/smoke.sh` is **modified** to detect `.tar.gz` vs `.zip` and to accept an optional `--launcher <relpath>` flag; default behaviour for the linux-x86_64 archive is unchanged.
- Create: `smoke/smoke.ps1` — PowerShell equivalent that extracts the windows-x86_64 zip into a temp dir, runs `bin\nocs.bat`, polls `http://localhost:8080/`, and tails `out.log` on failure.
- Create: `smoke/qemu-arm64-smoke.sh` — best-effort wrapper that uses `qemu-aarch64-static` (binfmt) to launch the arm64 launcher; exits 0 with a `SKIPPED` log if QEMU is missing or fails to register binfmt for `bin/java`.

**New CI workflows:**

- Modify: `.github/workflows/ci.yml` — restructure jobs:
  - `build-linux`: builds all three archives, smoke-tests linux-x86_64, uploads the three archives + SHA-256 sums as a single artifact named `nocs-archives`.
  - `smoke-windows`: depends on `build-linux`, runs on `windows-latest`, downloads the artifact, runs `smoke/smoke.ps1` against the windows zip.
  - `smoke-arm64-qemu`: depends on `build-linux`, runs on `ubuntu-latest`, sets up QEMU, runs `smoke/qemu-arm64-smoke.sh`. Marked `continue-on-error: true` so a flaky QEMU run does not block PRs; failure is surfaced as a warning annotation.
- Create: `.github/workflows/release.yml` — triggered by `push: tags: ['v*']`; checkout, set up JDK 25, run `./gradlew --no-daemon runtimeAll verifyArchiveSize`, compute `SHA256SUMS.txt`, and call `softprops/action-gh-release@v2` to publish a draft release with the four files (three archives + checksum file). Release body is templated from `docs/RELEASE_NOTES_TEMPLATE.md`.

**New docs:**

- Create: `docs/RELEASE_NOTES_TEMPLATE.md` — short markdown template referenced by the release workflow.
- Modify: `README.md` — replace the "Install (release archives, when published)" section with one snippet per platform plus a checksum-verification snippet.

---

## Tasks

Each task is self-contained: files listed, ordered steps with complete code, exact commands with expected output, and a commit at the end. Steps that mutate `build.gradle.kts` always show the full replacement block, not a diff, because the engineer may run them out of order.

---

### Task 1: Pin JDK 25 archive URLs and switch `runtime { }` to multi-platform

**Files:**
- Modify: `build.gradle.kts`

The pinned JDK is **Temurin 25.0.2+10** (latest GA at plan time, Feb 2026 release). URLs are the direct GitHub release assets, which Adoptium guarantees stable across mirrors. Bumping the version later is a one-line change to `jdk25Version`.

- [ ] **Step 1.1: Replace the entire `runtime { ... }` block in `build.gradle.kts`**

Open `build.gradle.kts`. Locate the existing block (lines ~51-63, starting with `runtime {` and ending with the closing `}` before `tasks.register<Tar>("runtimeTarGz")`). Replace it with:

```kotlin
val jdk25Version = "25.0.2"
val jdk25Build = "10"
val jdk25Tag = "jdk-${jdk25Version}%2B${jdk25Build}"
val jdk25Base = "https://github.com/adoptium/temurin25-binaries/releases/download/${jdk25Tag}"

val jdkUrls = mapOf(
    "linux-x86_64" to "${jdk25Base}/OpenJDK25U-jdk_x64_linux_hotspot_${jdk25Version}_${jdk25Build}.tar.gz",
    "linux-arm64" to "${jdk25Base}/OpenJDK25U-jdk_aarch64_linux_hotspot_${jdk25Version}_${jdk25Build}.tar.gz",
    "windows-x86_64" to "${jdk25Base}/OpenJDK25U-jdk_x64_windows_hotspot_${jdk25Version}_${jdk25Build}.zip",
)

runtime {
    options.set(listOf("--strip-debug", "--compress", "2", "--no-header-files", "--no-man-pages"))
    modules.set(
        listOf(
            "java.base", "java.desktop", "java.instrument", "java.logging",
            "java.management", "java.naming", "java.net.http", "java.prefs",
            "java.security.jgss", "java.sql", "java.xml",
            "jdk.crypto.ec", "jdk.jdi", "jdk.unsupported",
        ),
    )
    // The plugin appends "-<targetName>" to imageDir, so this becomes
    // build/image/nocs-linux-x86_64, build/image/nocs-linux-arm64, build/image/nocs-windows-x86_64.
    imageDir.set(layout.buildDirectory.dir("image/nocs").get().asFile)

    targetPlatform("linux-x86_64") {
        setJdkHome(jdkDownload(jdkUrls["linux-x86_64"]))
    }
    targetPlatform("linux-arm64") {
        setJdkHome(jdkDownload(jdkUrls["linux-arm64"]))
    }
    targetPlatform("windows-x86_64") {
        setJdkHome(jdkDownload(jdkUrls["windows-x86_64"]))
    }
}
```

Notes:
- The 2-arg `targetPlatform(name, jdkHome)` form takes a *local path*, not a URL. To download a JDK we must use the closure form and call `jdkDownload(url)` — a method on `TargetPlatform` that downloads + unpacks the archive and returns the local JDK directory path.
- We drop the old single-platform `imageZip` because, with `targetPlatform`, the plugin's built-in zipping is per-target and we replace it entirely with our own Tar/Zip tasks in Task 2 (so we get tar.gz on Linux and zip on Windows, not zip everywhere).
- Downloaded JDKs cache under `build/jdks/<targetName>/` by default; safe to delete with `gradle clean` if you need to re-pull.
- If Kotlin DSL fails to resolve `setJdkHome` inside the closure (it expects `Action<TargetPlatform>` but resolution can be ambiguous), fall back to `jdkHome = jdkDownload(...)` or qualify with `(this as org.beryx.runtime.data.TargetPlatform).setJdkHome(...)`.

- [ ] **Step 1.2: Remove the existing `runtimeTarGz` task — Task 2 replaces it**

In the same edit, delete the entire `tasks.register<Tar>("runtimeTarGz") { ... }` block at the bottom of `build.gradle.kts`. We rebuild it (split into three tasks plus an alias) in Task 2.

- [ ] **Step 1.3: Verify the build script compiles and the plugin downloads the foreign JDKs**

Run: `./gradlew --no-daemon runtime --info`

Expected on first run: `BUILD SUCCESSFUL`. The `--info` output contains three lines like `Downloading from https://github.com/adoptium/temurin25-binaries/releases/download/jdk-25.0.2%2B10/...` (one per platform). Subsequent runs reuse Gradle's user cache (default `~/.gradle/caches/`) and finish in seconds.

After success:

```bash
ls -1 build/image/
```

Expected output (exactly three directories, no other files):

```
nocs-linux-arm64
nocs-linux-x86_64
nocs-windows-x86_64
```

And inside each:

```bash
ls build/image/nocs-linux-x86_64/bin
ls build/image/nocs-linux-arm64/bin
ls build/image/nocs-windows-x86_64/bin
```

Each must contain `nocs`, `nocs.bat`, and a runtime `java` (or `java.exe` for the windows image).

- [ ] **Step 1.4: Confirm the windows image's `java.exe` is actually a Windows binary**

Run: `file build/image/nocs-windows-x86_64/bin/java.exe`

Expected: contains `PE32+ executable (console) x86-64, for MS Windows`.

Run: `file build/image/nocs-linux-arm64/bin/java`

Expected: contains `ELF 64-bit LSB ... ARM aarch64`.

If either check fails, the wrong JDK was downloaded — re-check the URLs in Step 1.1.

- [ ] **Step 1.5: Commit**

```bash
git add build.gradle.kts
git commit -m "build: switch jlink runtime to multi-platform target images"
```

---

### Task 2: Per-platform archive tasks + `runtimeAll` aggregate

**Files:**
- Modify: `build.gradle.kts`

We want three archives:
- `build/distributions/nocs-<version>-linux-x86_64.tar.gz`
- `build/distributions/nocs-<version>-linux-arm64.tar.gz`
- `build/distributions/nocs-<version>-windows-x86_64.zip`

Linux archives must keep `bin/nocs` (executable bit) and drop `bin/nocs.bat`. The Windows archive must keep `bin\nocs.bat` and drop `bin/nocs`. Files inside `lib/runtime/bin/` must keep their executable bits on Linux; on Windows, only `.exe` and `.dll` files exist anyway.

- [ ] **Step 2.1: Append the three archive tasks + aggregate to `build.gradle.kts`**

After the `runtime { ... }` block, append:

```kotlin
fun isExecutableInsideImage(relativePath: String): Boolean {
    if (relativePath.startsWith("bin/")) {
        return !relativePath.endsWith(".bat")
    }
    if (relativePath.startsWith("lib/runtime/bin/")) {
        return !relativePath.endsWith(".dll") && !relativePath.endsWith(".exe")
    }
    // jspawnhelper and similar live under lib/runtime/lib/ on Linux/macOS images, with no extension
    if (relativePath.startsWith("lib/runtime/lib/") && !relativePath.substringAfterLast('/').contains('.')) {
        return true
    }
    return false
}

fun org.gradle.api.file.CopySpec.applyUnixPermissions() {
    eachFile {
        if (isExecutableInsideImage(relativePath.pathString)) {
            permissions { unix("755") }
        } else {
            permissions { unix("644") }
        }
    }
    dirPermissions { unix("755") }
}

tasks.register<Tar>("runtimeTarLinuxX64") {
    group = "distribution"
    description = "Build the linux-x86_64 self-contained tar.gz archive."
    dependsOn("runtime")
    compression = Compression.GZIP
    archiveFileName.set("nocs-${project.version}-linux-x86_64.tar.gz")
    destinationDirectory.set(layout.buildDirectory.dir("distributions"))
    into("nocs-${project.version}") {
        from(layout.buildDirectory.dir("image/nocs-linux-x86_64")) {
            exclude("bin/nocs.bat")
        }
        applyUnixPermissions()
    }
}

tasks.register<Tar>("runtimeTarLinuxArm64") {
    group = "distribution"
    description = "Build the linux-arm64 self-contained tar.gz archive."
    dependsOn("runtime")
    compression = Compression.GZIP
    archiveFileName.set("nocs-${project.version}-linux-arm64.tar.gz")
    destinationDirectory.set(layout.buildDirectory.dir("distributions"))
    into("nocs-${project.version}") {
        from(layout.buildDirectory.dir("image/nocs-linux-arm64")) {
            exclude("bin/nocs.bat")
        }
        applyUnixPermissions()
    }
}

tasks.register<Zip>("runtimeZipWindowsX64") {
    group = "distribution"
    description = "Build the windows-x86_64 self-contained zip archive."
    dependsOn("runtime")
    archiveFileName.set("nocs-${project.version}-windows-x86_64.zip")
    destinationDirectory.set(layout.buildDirectory.dir("distributions"))
    into("nocs-${project.version}") {
        from(layout.buildDirectory.dir("image/nocs-windows-x86_64")) {
            exclude("bin/nocs")
        }
    }
}

tasks.register("runtimeAll") {
    group = "distribution"
    description = "Build all three platform archives (linux-x86_64, linux-arm64, windows-x86_64)."
    dependsOn("runtimeTarLinuxX64", "runtimeTarLinuxArm64", "runtimeZipWindowsX64")
}

// Backwards-compatible alias used by the pre-Plan-I CI workflow and any developer scripts
// that still call `./gradlew runtimeTarGz`. Safe to remove once all callers migrate.
tasks.register("runtimeTarGz") {
    group = "distribution"
    description = "Deprecated. Alias for runtimeTarLinuxX64. Use runtimeTarLinuxX64 directly."
    dependsOn("runtimeTarLinuxX64")
    doFirst {
        logger.warn(
            "Task ':runtimeTarGz' is deprecated; call ':runtimeTarLinuxX64' or ':runtimeAll' instead.",
        )
    }
}
```

- [ ] **Step 2.2: Build the three archives**

Run: `./gradlew --no-daemon runtimeAll`

Expected: `BUILD SUCCESSFUL`. After it completes:

```bash
ls -1 build/distributions/
```

Expected output (the order may differ):

```
nocs-0.1.0-SNAPSHOT-linux-arm64.tar.gz
nocs-0.1.0-SNAPSHOT-linux-x86_64.tar.gz
nocs-0.1.0-SNAPSHOT-windows-x86_64.zip
```

- [ ] **Step 2.3: Verify each archive contains the right launchers and only the right launchers**

Run:

```bash
tar -tzf build/distributions/nocs-0.1.0-SNAPSHOT-linux-x86_64.tar.gz | grep -E 'bin/nocs(\.bat)?$' | sort
```

Expected output (exactly one line, no `.bat`):

```
nocs-0.1.0-SNAPSHOT/bin/nocs
```

Run:

```bash
tar -tzf build/distributions/nocs-0.1.0-SNAPSHOT-linux-arm64.tar.gz | grep -E 'bin/nocs(\.bat)?$' | sort
```

Expected: same single line.

Run:

```bash
unzip -l build/distributions/nocs-0.1.0-SNAPSHOT-windows-x86_64.zip | grep -E 'bin/nocs(\.bat)?'
```

Expected: exactly one match ending in `bin/nocs.bat` (no plain `bin/nocs`).

- [ ] **Step 2.4: Verify file permissions in the linux tar.gz**

Run:

```bash
tar -tvzf build/distributions/nocs-0.1.0-SNAPSHOT-linux-x86_64.tar.gz | awk '$NF ~ /bin\/(nocs|java)$/ {print $1, $NF}'
```

Expected: each listed file's mode begins with `-rwxr-xr-x` (i.e. 755). For example:

```
-rwxr-xr-x nocs-0.1.0-SNAPSHOT/bin/nocs
-rwxr-xr-x nocs-0.1.0-SNAPSHOT/bin/java
-rwxr-xr-x nocs-0.1.0-SNAPSHOT/lib/runtime/bin/java
```

Run:

```bash
tar -tvzf build/distributions/nocs-0.1.0-SNAPSHOT-linux-x86_64.tar.gz | awk '$NF ~ /\.jar$/' | head -3
```

Expected: each `.jar` is `644` (`-rw-r--r--`).

- [ ] **Step 2.5: Verify the legacy alias still works**

Run: `./gradlew --no-daemon runtimeTarGz`

Expected: `BUILD SUCCESSFUL`, log contains the deprecation warning string `Task ':runtimeTarGz' is deprecated`. The output file `nocs-0.1.0-SNAPSHOT-linux-x86_64.tar.gz` still exists in `build/distributions/`.

- [ ] **Step 2.6: Commit**

```bash
git add build.gradle.kts
git commit -m "build: per-platform archive tasks + runtimeAll aggregate"
```

---

### Task 3: Polish Windows launcher with `NOCS_DATA_DIR` default

**Files:**
- Read-only inspection: `build/image/nocs-windows-x86_64/bin/nocs.bat` (generated)
- Modify: `build.gradle.kts` (add a post-process step on the windows image)

The Linux `bin/nocs` script delegates to `dev.nocs.NocsApplication` which reads `NOCS_DATA_DIR` via `DataDirBootstrap` and falls back to `$XDG_DATA_HOME/nocs`. On Windows there is no XDG, and `DataDirBootstrap.windowsDefault()` already targets `%APPDATA%\nocs` — no Java change needed. We only adjust the launcher so a user who double-clicks `nocs.bat` (no env vars set) gets the same data dir a CMD invocation would.

We deliberately **do not** override Gradle's `WindowsStartScriptGenerator.template` via internal API. Instead we patch the generated `bin/nocs.bat` in `build/image/nocs-windows-x86_64/` with a small `doLast` action wired between `runtime` and `runtimeZipWindowsX64`. This keeps us off Gradle's `org.gradle.api.internal.*` packages and is trivially debuggable (cat the file, see the change).

- [ ] **Step 3.1: Inspect the default launcher to find a stable insertion anchor**

Run: `grep -n -E '^set APP_HOME=' build/image/nocs-windows-x86_64/bin/nocs.bat`

Expected: exactly one matching line, looking something like `8:set APP_HOME=%DIRNAME%..`. We will insert our defaulting line after the `for %%i in (...) do set APP_HOME=%%~fi` block (which always follows it).

If `grep` finds zero or more than one match, fail loudly — the upstream template changed and Step 3.2 needs adjusting.

- [ ] **Step 3.2: Add `patchWindowsLauncher` task to `build.gradle.kts`**

Append (after the `runtime { ... }` block, before `runtimeZipWindowsX64`):

```kotlin
tasks.register("patchWindowsLauncher") {
    group = "distribution"
    description = "Inject NOCS_DATA_DIR default into the generated windows launcher."
    dependsOn("runtime")
    val launcher = layout.buildDirectory.file("image/nocs-windows-x86_64/bin/nocs.bat")
    inputs.file(launcher)
    outputs.file(launcher)
    doLast {
        val file = launcher.get().asFile
        val original = file.readText(Charsets.ISO_8859_1)
        val marker = "NOCS_DATA_DIR_DEFAULT"
        if (original.contains(marker)) {
            logger.lifecycle("nocs.bat already patched; skipping.")
            return@doLast
        }
        val anchor = Regex("""(?m)^for %%i in \("%APP_HOME%"\) do set APP_HOME=%%~fi\s*$""")
        val match = anchor.find(original)
            ?: throw GradleException(
                "Could not find APP_HOME anchor in nocs.bat — Gradle's windows template changed; " +
                    "re-run Step 3.1 to pick a new anchor.",
            )
        val injection = buildString {
            append(System.lineSeparator())
            append("@rem ${marker}: default NOCS data dir if the user did not set one.")
            append(System.lineSeparator())
            append("if not defined NOCS_DATA_DIR set \"NOCS_DATA_DIR=%APPDATA%\\nocs\"")
            append(System.lineSeparator())
        }
        val patched = original.substring(0, match.range.last + 1) +
            injection +
            original.substring(match.range.last + 1)
        file.writeText(patched, Charsets.ISO_8859_1)
        logger.lifecycle("Patched ${file.name} with NOCS_DATA_DIR default.")
    }
}
```

We read/write as ISO-8859-1 so we never introduce a BOM or alter Gradle's existing CRLF line endings. The injected lines use `System.lineSeparator()` so the patch matches the build host's convention; on Windows runners that's already CRLF, on Linux runners that's LF — but the file is going into a `.zip` whose final consumer is Windows. Windows `cmd.exe` accepts LF inside a CRLF file fine, so this is safe.

- [ ] **Step 3.3: Wire `runtimeZipWindowsX64` to depend on the patch task**

Find the `runtimeZipWindowsX64` task you created in Task 2. Change its `dependsOn("runtime")` line to:

```kotlin
    dependsOn("runtime", "patchWindowsLauncher")
```

Leave the rest of the task definition untouched.

- [ ] **Step 3.4: Re-build and verify the launcher contains the NOCS line**

Run:

```bash
./gradlew --no-daemon clean runtimeZipWindowsX64
unzip -p build/distributions/nocs-0.1.0-SNAPSHOT-windows-x86_64.zip 'nocs-0.1.0-SNAPSHOT/bin/nocs.bat' | grep -n 'NOCS_DATA_DIR'
```

Expected: at least two matching lines (the comment marker and the `if not defined ...` line):

```
N:@rem NOCS_DATA_DIR_DEFAULT: default NOCS data dir if the user did not set one.
N+1:if not defined NOCS_DATA_DIR set "NOCS_DATA_DIR=%APPDATA%\nocs"
```

- [ ] **Step 3.5: Idempotency check — running twice must not double-patch**

Run: `./gradlew --no-daemon patchWindowsLauncher`

Expected: `nocs.bat already patched; skipping.` log line and `BUILD SUCCESSFUL`.

Re-confirm:

```bash
grep -c 'NOCS_DATA_DIR_DEFAULT' build/image/nocs-windows-x86_64/bin/nocs.bat
```

Expected: `1` (the marker appears exactly once even after the second run).

- [ ] **Step 3.6: Confirm the linux launcher is unchanged**

Run:

```bash
tar -xzOf build/distributions/nocs-0.1.0-SNAPSHOT-linux-x86_64.tar.gz nocs-0.1.0-SNAPSHOT/bin/nocs | head -5
```

Expected: a normal Bash launcher beginning with `#!/usr/bin/env sh` (Gradle's default) — no NOCS-specific marker. We deliberately do not customise the Linux launcher since `DataDirBootstrap` already handles `XDG_DATA_HOME`.

- [ ] **Step 3.7: Commit**

```bash
git add build.gradle.kts
git commit -m "build: patch windows launcher to default NOCS_DATA_DIR to %APPDATA%\\nocs"
```

---

### Task 4: Generalise `smoke/smoke.sh` to handle both `.tar.gz` and `.zip`

**Files:**
- Modify: `smoke/smoke.sh`

The existing script (Plan A) already extracts a `.tar.gz` and curls `http://localhost:8080/`. We extend it to:
1. Detect archive type by extension and use `tar` or `unzip` accordingly.
2. Accept `--launcher <relpath>` (default `bin/nocs`) so the same script smoke-tests Windows zips on a Linux runner via Wine if ever needed (we will not actually use Wine in CI; the optional flag is there for local debugging).
3. Bump the wait timeout to 60 s — the arm64 image under QEMU starts much slower than native.

- [ ] **Step 4.1: Replace `smoke/smoke.sh` with the extended version**

Overwrite the file with:

```bash
#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: $0 [--launcher <relative-path>] <archive>" >&2
  echo "  archive: .tar.gz or .zip produced by ./gradlew runtimeAll" >&2
  exit 2
}

LAUNCHER="bin/nocs"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --launcher)
      [ "$#" -ge 2 ] || usage
      LAUNCHER="$2"
      shift 2
      ;;
    -h|--help)
      usage
      ;;
    *)
      ARCHIVE="${ARCHIVE:-$1}"
      shift
      ;;
  esac
done

[ -n "${ARCHIVE:-}" ] || usage
[ -f "$ARCHIVE" ] || { echo "archive not found: $ARCHIVE" >&2; exit 2; }

WORK=$(mktemp -d)
PID=""
trap 'if [ -n "$PID" ]; then kill "$PID" 2>/dev/null || true; fi; rm -rf "$WORK"' EXIT

case "$ARCHIVE" in
  *.tar.gz|*.tgz)
    tar -C "$WORK" -xzf "$ARCHIVE"
    ;;
  *.zip)
    unzip -q -d "$WORK" "$ARCHIVE"
    ;;
  *)
    echo "unsupported archive type: $ARCHIVE" >&2
    exit 2
    ;;
esac

DIR=$(find "$WORK" -maxdepth 1 -mindepth 1 -type d)
[ -d "$DIR" ] || { echo "no top-level directory inside archive" >&2; exit 2; }

LAUNCHER_PATH="$DIR/$LAUNCHER"
[ -x "$LAUNCHER_PATH" ] || chmod +x "$LAUNCHER_PATH" 2>/dev/null || true
[ -f "$LAUNCHER_PATH" ] || { echo "launcher missing: $LAUNCHER_PATH" >&2; exit 2; }

NOCS_DATA_DIR=$(mktemp -d) "$LAUNCHER_PATH" > "$WORK/out.log" 2>&1 &
PID=$!

for i in $(seq 1 60); do
  if curl -fsS http://localhost:8080/ >/dev/null 2>&1; then
    echo "NOCS is up after ${i}s (archive=$ARCHIVE launcher=$LAUNCHER)"
    exit 0
  fi
  if ! kill -0 "$PID" 2>/dev/null; then
    echo "launcher exited before serving HTTP; logs:" >&2
    cat "$WORK/out.log" >&2
    exit 1
  fi
  sleep 1
done

echo "NOCS did not start within 60s; logs:" >&2
cat "$WORK/out.log" >&2
exit 1
```

Make sure it stays executable:

```bash
chmod +x smoke/smoke.sh
```

- [ ] **Step 4.2: Re-run the smoke test against the linux-x86_64 archive**

Run: `./smoke/smoke.sh build/distributions/nocs-0.1.0-SNAPSHOT-linux-x86_64.tar.gz`

Expected output: `NOCS is up after Ns (archive=... launcher=bin/nocs)` for some small N.

- [ ] **Step 4.3: Confirm the script rejects unknown archive types and missing files**

Run: `./smoke/smoke.sh /tmp/no-such-file.tar.gz; echo $?`

Expected: prints `archive not found: ...` and exit code `2`.

Run: `touch /tmp/foo.7z; ./smoke/smoke.sh /tmp/foo.7z; echo $?; rm /tmp/foo.7z`

Expected: prints `unsupported archive type: ...` and exit code `2`.

- [ ] **Step 4.4: Commit**

```bash
git add smoke/smoke.sh
git commit -m "smoke: support .zip + custom launcher path + tighter exit handling"
```

---

### Task 5: PowerShell smoke script for the Windows zip

**Files:**
- Create: `smoke/smoke.ps1`

Same control-flow as `smoke/smoke.sh` but in PowerShell, intended to run on `windows-latest` GitHub-hosted runners. Polls `http://localhost:8080/` for up to 60 s and tails `out.log` on failure.

- [ ] **Step 5.1: Create `smoke/smoke.ps1`**

```powershell
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true, Position=0)]
    [string]$ArchivePath,
    [string]$Launcher = "bin\nocs.bat"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $ArchivePath)) {
    Write-Error "archive not found: $ArchivePath"
    exit 2
}

$work = New-Item -ItemType Directory -Path (Join-Path $env:TEMP ([System.Guid]::NewGuid().ToString()))
$dataDir = New-Item -ItemType Directory -Path (Join-Path $env:TEMP ([System.Guid]::NewGuid().ToString()))
$logPath = Join-Path $work "out.log"
$proc = $null

try {
    Expand-Archive -Path $ArchivePath -DestinationPath $work -Force

    $top = Get-ChildItem -Path $work -Directory | Select-Object -First 1
    if (-not $top) { throw "no top-level directory inside archive" }

    $launcherPath = Join-Path $top.FullName $Launcher
    if (-not (Test-Path $launcherPath)) { throw "launcher missing: $launcherPath" }

    $env:NOCS_DATA_DIR = $dataDir.FullName

    $proc = Start-Process -FilePath $launcherPath `
        -RedirectStandardOutput $logPath `
        -RedirectStandardError $logPath `
        -PassThru -WindowStyle Hidden

    for ($i = 1; $i -le 60; $i++) {
        try {
            $resp = Invoke-WebRequest -Uri "http://localhost:8080/" -UseBasicParsing -TimeoutSec 2
            if ($resp.StatusCode -eq 200) {
                Write-Host "NOCS is up after ${i}s (archive=$ArchivePath launcher=$Launcher)"
                exit 0
            }
        } catch {
            # not ready yet
        }
        if ($proc.HasExited) {
            Write-Error "launcher exited before serving HTTP; logs:"
            Get-Content $logPath | Write-Host
            exit 1
        }
        Start-Sleep -Seconds 1
    }

    Write-Error "NOCS did not start within 60s; logs:"
    Get-Content $logPath | Write-Host
    exit 1
}
finally {
    if ($proc -ne $null -and -not $proc.HasExited) {
        try { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } catch {}
    }
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $work
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $dataDir
}
```

- [ ] **Step 5.2: (Optional, only if a Windows machine is available locally) verify the script runs**

If you're on Windows, run: `pwsh smoke/smoke.ps1 build/distributions/nocs-0.1.0-SNAPSHOT-windows-x86_64.zip`

Expected: `NOCS is up after Ns ...`. Otherwise rely on the CI job (Task 7) for verification.

- [ ] **Step 5.3: Commit**

```bash
git add smoke/smoke.ps1
git commit -m "smoke: PowerShell smoke script for windows-x86_64 zip"
```

---

### Task 6: Best-effort QEMU smoke for the linux-arm64 archive

**Files:**
- Create: `smoke/qemu-arm64-smoke.sh`

The arm64 archive cannot be tested natively on `ubuntu-latest`. We use `qemu-aarch64-static` and Linux `binfmt_misc` to transparently run aarch64 binaries. If the runner's kernel does not support binfmt_misc registration (or if QEMU is missing), the script logs `SKIPPED` and exits 0 so it does not gate PRs. The CI job that calls it sets `continue-on-error: true` regardless.

- [ ] **Step 6.1: Create `smoke/qemu-arm64-smoke.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

ARCHIVE="${1:-}"
if [ -z "$ARCHIVE" ]; then
  echo "usage: $0 <linux-arm64.tar.gz>" >&2
  exit 2
fi

if ! command -v qemu-aarch64-static >/dev/null 2>&1; then
  echo "SKIPPED: qemu-aarch64-static not installed; run 'sudo apt-get install -y qemu-user-static' first." >&2
  exit 0
fi

if [ ! -e /proc/sys/fs/binfmt_misc/qemu-aarch64 ] && [ ! -e /proc/sys/fs/binfmt_misc/aarch64 ]; then
  echo "SKIPPED: aarch64 binfmt_misc not registered; on GitHub Actions use docker/setup-qemu-action@v3 first." >&2
  exit 0
fi

WORK=$(mktemp -d)
PID=""
trap 'if [ -n "$PID" ]; then kill "$PID" 2>/dev/null || true; fi; rm -rf "$WORK"' EXIT

tar -C "$WORK" -xzf "$ARCHIVE"
DIR=$(find "$WORK" -maxdepth 1 -mindepth 1 -type d)

# Sanity-check: the bundled java MUST be aarch64 ELF
JAVA_BIN="$DIR/bin/java"
file "$JAVA_BIN" | grep -q 'ARM aarch64' || {
  echo "FAIL: $JAVA_BIN is not aarch64 ELF (image was built wrong)" >&2
  file "$JAVA_BIN" >&2
  exit 1
}

NOCS_DATA_DIR=$(mktemp -d) "$DIR/bin/nocs" > "$WORK/out.log" 2>&1 &
PID=$!

# QEMU is slow: allow 120 s
for i in $(seq 1 120); do
  if curl -fsS http://localhost:8080/ >/dev/null 2>&1; then
    echo "NOCS-arm64 is up under QEMU after ${i}s"
    exit 0
  fi
  if ! kill -0 "$PID" 2>/dev/null; then
    echo "launcher exited before serving HTTP; logs:" >&2
    cat "$WORK/out.log" >&2
    exit 1
  fi
  sleep 1
done

echo "NOCS-arm64 did not start within 120s under QEMU; logs:" >&2
cat "$WORK/out.log" >&2
exit 1
```

Make it executable:

```bash
chmod +x smoke/qemu-arm64-smoke.sh
```

- [ ] **Step 6.2: Local dry-run (skipped path)**

If QEMU is not installed locally:

```bash
./smoke/qemu-arm64-smoke.sh build/distributions/nocs-0.1.0-SNAPSHOT-linux-arm64.tar.gz
```

Expected: prints `SKIPPED: ...` and exits 0.

If QEMU is installed and binfmt is registered (Debian/Ubuntu: `sudo apt-get install -y qemu-user-static binfmt-support && sudo update-binfmts --enable qemu-aarch64`), expected: `NOCS-arm64 is up under QEMU after Ns`.

- [ ] **Step 6.3: Commit**

```bash
git add smoke/qemu-arm64-smoke.sh
git commit -m "smoke: best-effort QEMU smoke for linux-arm64 archive"
```

---

### Task 7: `verifyArchiveSize` Gradle task (≤150 MB envelope)

**Files:**
- Modify: `build.gradle.kts`

Spec §14.1 sets the per-archive envelope at "under ~150 MB". We enforce 150 × 1024 × 1024 bytes (157 286 400) as a hard upper bound on each of the three archives and fail `runtimeAll` if any exceeds it. The current jlink images come in well under (typically 60-80 MB compressed), so this is a regression detector.

- [ ] **Step 7.1: Append `verifyArchiveSize` to `build.gradle.kts`**

```kotlin
val maxArchiveBytes = 150L * 1024L * 1024L

tasks.register("verifyArchiveSize") {
    group = "verification"
    description = "Fail if any release archive exceeds the spec §14.1 envelope (150 MB)."
    dependsOn("runtimeAll")
    doLast {
        val dir = layout.buildDirectory.dir("distributions").get().asFile
        val archives = listOf(
            "nocs-${project.version}-linux-x86_64.tar.gz",
            "nocs-${project.version}-linux-arm64.tar.gz",
            "nocs-${project.version}-windows-x86_64.zip",
        ).map { dir.resolve(it) }

        val problems = mutableListOf<String>()
        archives.forEach { f ->
            if (!f.exists()) {
                problems += "missing: ${f.name}"
            } else {
                val sizeMb = f.length().toDouble() / (1024.0 * 1024.0)
                logger.lifecycle(String.format("%-50s %6.1f MB", f.name, sizeMb))
                if (f.length() > maxArchiveBytes) {
                    problems += String.format(
                        "%s exceeds 150 MB envelope (%.1f MB)", f.name, sizeMb,
                    )
                }
            }
        }
        if (problems.isNotEmpty()) {
            throw GradleException(
                "Archive size check failed:\n  - " + problems.joinToString("\n  - "),
            )
        }
    }
}
```

- [ ] **Step 7.2: Run it**

Run: `./gradlew --no-daemon verifyArchiveSize`

Expected: three log lines like

```
nocs-0.1.0-SNAPSHOT-linux-x86_64.tar.gz             67.4 MB
nocs-0.1.0-SNAPSHOT-linux-arm64.tar.gz              66.1 MB
nocs-0.1.0-SNAPSHOT-windows-x86_64.zip              71.8 MB
```

followed by `BUILD SUCCESSFUL`. Exact sizes will vary; all three must be < 150 MB.

If any exceeds the envelope, **stop** and revisit `runtime { modules.set(...) }` to drop unused JDK modules — do not raise the limit.

- [ ] **Step 7.3: Commit**

```bash
git add build.gradle.kts
git commit -m "build: verifyArchiveSize enforces spec §14.1 150MB envelope"
```

---

### Task 8: CI workflow — multi-arch build + matrix smoke

**Files:**
- Modify: `.github/workflows/ci.yml`

Restructure into three jobs. The `build-linux` job replaces the existing single-job workflow.

- [ ] **Step 8.1: Replace `.github/workflows/ci.yml` with the multi-job version**

```yaml
name: CI

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]

jobs:
  build-linux:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up JDK 25
        uses: actions/setup-java@v4
        with:
          distribution: temurin
          java-version: 25

      - name: Set up Gradle
        uses: gradle/actions/setup-gradle@v4

      - name: Install INDI
        run: |
          sudo apt-get update
          sudo apt-get install -y indi-bin
          which indiserver indi_simulator_telescope indi_simulator_ccd indi_simulator_focus indi_simulator_wheel

      - name: Run tests
        env:
          NOCS_INDI_BIN: "1"
        run: ./gradlew --no-daemon check

      - name: Build all platform archives
        run: ./gradlew --no-daemon runtimeAll verifyArchiveSize

      - name: Smoke-test linux-x86_64 archive
        run: ./smoke/smoke.sh build/distributions/nocs-*-linux-x86_64.tar.gz

      - name: Compute SHA-256 sums
        run: |
          cd build/distributions
          sha256sum nocs-*-linux-x86_64.tar.gz nocs-*-linux-arm64.tar.gz nocs-*-windows-x86_64.zip > SHA256SUMS.txt
          cat SHA256SUMS.txt

      - name: Upload archives
        if: success()
        uses: actions/upload-artifact@v4
        with:
          name: nocs-archives
          path: |
            build/distributions/nocs-*-linux-x86_64.tar.gz
            build/distributions/nocs-*-linux-arm64.tar.gz
            build/distributions/nocs-*-windows-x86_64.zip
            build/distributions/SHA256SUMS.txt
          if-no-files-found: error

  smoke-windows:
    needs: build-linux
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4

      - name: Download archives
        uses: actions/download-artifact@v4
        with:
          name: nocs-archives
          path: dist

      - name: Smoke-test windows-x86_64 zip
        shell: pwsh
        run: |
          $zip = Get-ChildItem dist\nocs-*-windows-x86_64.zip | Select-Object -First 1
          if (-not $zip) { throw "windows zip not found in artifact" }
          .\smoke\smoke.ps1 -ArchivePath $zip.FullName

  smoke-arm64-qemu:
    needs: build-linux
    runs-on: ubuntu-latest
    continue-on-error: true
    steps:
      - uses: actions/checkout@v4

      - name: Download archives
        uses: actions/download-artifact@v4
        with:
          name: nocs-archives
          path: dist

      - name: Set up QEMU (aarch64)
        uses: docker/setup-qemu-action@v3
        with:
          platforms: arm64

      - name: Install qemu-user-static (host-mode)
        run: |
          sudo apt-get update
          sudo apt-get install -y qemu-user-static binfmt-support
          # Re-register with the host-installed qemu so we can run aarch64 ELFs directly,
          # not only inside containers. setup-qemu-action only registers binfmt for Docker.
          sudo update-binfmts --import qemu-aarch64 || true

      - name: Smoke-test linux-arm64 tarball under QEMU
        run: |
          tarball=$(ls dist/nocs-*-linux-arm64.tar.gz | head -n 1)
          ./smoke/qemu-arm64-smoke.sh "$tarball"
```

- [ ] **Step 8.2: Validate the YAML locally**

If `actionlint` is installed (`go install github.com/rhysd/actionlint/cmd/actionlint@latest`), run:

```bash
actionlint .github/workflows/ci.yml
```

Expected: no output (success).

If `actionlint` is not installed, at least lint with Python's YAML parser:

```bash
python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml'))" && echo OK
```

Expected: `OK`.

- [ ] **Step 8.3: Mirror the CI invocation locally to catch regressions**

```bash
./gradlew --no-daemon check
./gradlew --no-daemon runtimeAll verifyArchiveSize
./smoke/smoke.sh build/distributions/nocs-*-linux-x86_64.tar.gz
( cd build/distributions && sha256sum nocs-*-linux-x86_64.tar.gz nocs-*-linux-arm64.tar.gz nocs-*-windows-x86_64.zip > SHA256SUMS.txt && cat SHA256SUMS.txt )
```

Expected: each command exits 0; `SHA256SUMS.txt` has three lines.

- [ ] **Step 8.4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: multi-arch build with windows + qemu-arm64 smoke matrix"
```

---

### Task 9: Release workflow (`v*` tag → GitHub Release)

**Files:**
- Create: `docs/RELEASE_NOTES_TEMPLATE.md`
- Create: `.github/workflows/release.yml`

The release workflow is intentionally separate from `ci.yml` so it stays simple and only fires on tag pushes. It re-builds (rather than reusing CI artifacts) so a release is always deterministic against the tagged source tree, not against the most recent main-branch CI run.

- [ ] **Step 9.1: Create `docs/RELEASE_NOTES_TEMPLATE.md`**

```markdown
# NOCS {VERSION}

> **Status:** Pre-release (v0.1 development series).

## Downloads

| Platform | Archive | SHA-256 |
|---|---|---|
| Linux x86_64 | `nocs-{VERSION}-linux-x86_64.tar.gz` | see `SHA256SUMS.txt` |
| Linux arm64 (Raspberry Pi 4/5) | `nocs-{VERSION}-linux-arm64.tar.gz` | see `SHA256SUMS.txt` |
| Windows x86_64 | `nocs-{VERSION}-windows-x86_64.zip` | see `SHA256SUMS.txt` |

Each archive is self-contained: bundled JDK 25 (Temurin), no system dependencies. Install = download, unpack, run `bin/nocs` (Linux) or `bin\nocs.bat` (Windows). On first run NOCS creates its data directory and prints a generated bearer token.

## Verify your download

```bash
sha256sum -c SHA256SUMS.txt --ignore-missing
```

## What's in this release

<!-- Edit this section before publishing the draft. -->

- ...
```

- [ ] **Step 9.2: Create `.github/workflows/release.yml`**

```yaml
name: Release

on:
  push:
    tags:
      - 'v*'

permissions:
  contents: write

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up JDK 25
        uses: actions/setup-java@v4
        with:
          distribution: temurin
          java-version: 25

      - name: Set up Gradle
        uses: gradle/actions/setup-gradle@v4

      - name: Build all platform archives
        run: ./gradlew --no-daemon runtimeAll verifyArchiveSize

      - name: Compute SHA-256 sums
        id: sums
        run: |
          cd build/distributions
          sha256sum nocs-*-linux-x86_64.tar.gz nocs-*-linux-arm64.tar.gz nocs-*-windows-x86_64.zip > SHA256SUMS.txt
          cat SHA256SUMS.txt

      - name: Render release notes
        id: notes
        run: |
          version="${GITHUB_REF_NAME#v}"
          sed "s/{VERSION}/${version}/g" docs/RELEASE_NOTES_TEMPLATE.md > release-notes.md
          cat release-notes.md

      - name: Publish draft GitHub Release
        uses: softprops/action-gh-release@v2
        with:
          draft: true
          name: "NOCS ${{ github.ref_name }}"
          body_path: release-notes.md
          fail_on_unmatched_files: true
          files: |
            build/distributions/nocs-*-linux-x86_64.tar.gz
            build/distributions/nocs-*-linux-arm64.tar.gz
            build/distributions/nocs-*-windows-x86_64.zip
            build/distributions/SHA256SUMS.txt
```

The release is published as a **draft** so a human can edit the notes (filling in "What's in this release") and click Publish. Once happy with the cycle, drop `draft: true` to auto-publish.

- [ ] **Step 9.3: Validate the YAML**

Run:

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml'))" && echo OK
```

Expected: `OK`.

- [ ] **Step 9.4: Dry-run by simulating the rendered notes locally**

Run:

```bash
sed 's/{VERSION}/0.1.0/g' docs/RELEASE_NOTES_TEMPLATE.md
```

Expected: a markdown document where every `{VERSION}` placeholder has been replaced with `0.1.0`.

- [ ] **Step 9.5: Commit**

```bash
git add docs/RELEASE_NOTES_TEMPLATE.md .github/workflows/release.yml
git commit -m "release: tag-driven workflow publishes multi-arch GitHub Release draft"
```

---

### Task 10: README install instructions for arm64 + Windows

**Files:**
- Modify: `README.md`

Replace the `## Install (release archives, when published)` section with one snippet per platform plus a checksum-verification example. Keep the surrounding text untouched.

- [ ] **Step 10.1: Replace the install section in `README.md`**

Locate the section `## Install (release archives, when published)` and the snippet that follows it (currently lines ~158-170 — but search by heading rather than line number in case other plans have already shifted things). Replace the entire section, up to but not including the next `##` heading, with:

```markdown
## Install (release archives)

Each release publishes three self-contained archives. Pick the one for your machine, unpack it, and run the launcher — no system JDK, no `sudo`, no package manager.

### Linux x86_64

```bash
VERSION=0.1.0    # replace with the release tag without the leading "v"
curl -LO https://github.com/jorjazo/nocs/releases/download/v${VERSION}/nocs-${VERSION}-linux-x86_64.tar.gz
tar xzf nocs-${VERSION}-linux-x86_64.tar.gz
cd nocs-${VERSION}
./bin/nocs
```

### Linux arm64 (Raspberry Pi 4 / 5)

```bash
VERSION=0.1.0
curl -LO https://github.com/jorjazo/nocs/releases/download/v${VERSION}/nocs-${VERSION}-linux-arm64.tar.gz
tar xzf nocs-${VERSION}-linux-arm64.tar.gz
cd nocs-${VERSION}
./bin/nocs
```

### Windows x86_64

In PowerShell:

```powershell
$VERSION = "0.1.0"
Invoke-WebRequest "https://github.com/jorjazo/nocs/releases/download/v$VERSION/nocs-$VERSION-windows-x86_64.zip" -OutFile "nocs.zip"
Expand-Archive nocs.zip -DestinationPath .
cd "nocs-$VERSION"
.\bin\nocs.bat
```

### Verify your download

Each release ships a `SHA256SUMS.txt` you can verify against:

```bash
curl -LO https://github.com/jorjazo/nocs/releases/download/v${VERSION}/SHA256SUMS.txt
sha256sum -c SHA256SUMS.txt --ignore-missing
```

(Windows: use `Get-FileHash <archive> -Algorithm SHA256` and compare against the matching line in `SHA256SUMS.txt`.)

On first run NOCS creates its data directory (`$XDG_DATA_HOME/nocs` on Linux, `%APPDATA%\nocs` on Windows), copies example configs, and prints a generated bearer token. Point a browser at `http://<host>:<port>/` and use the token for API calls.
```

- [ ] **Step 10.2: Verify the markdown still renders cleanly**

Run:

```bash
grep -nE '^## ' README.md | head -20
```

Expected: the heading list still includes `## Install (release archives)` (renamed) and the surrounding sections are intact.

- [ ] **Step 10.3: Commit**

```bash
git add README.md
git commit -m "docs: README install snippets for linux-arm64 and windows-x86_64"
```

---

### Task 11: Final verification

**Files:**
- (no edits — verification only)

- [ ] **Step 11.1: Clean build, full pipeline**

```bash
./gradlew --no-daemon clean check runtimeAll verifyArchiveSize
./smoke/smoke.sh build/distributions/nocs-*-linux-x86_64.tar.gz
( cd build/distributions && sha256sum nocs-*-linux-x86_64.tar.gz nocs-*-linux-arm64.tar.gz nocs-*-windows-x86_64.zip > SHA256SUMS.txt && cat SHA256SUMS.txt )
```

Expected: every command exits 0. `build/distributions/SHA256SUMS.txt` lists three files.

- [ ] **Step 11.2: Confirm artifact inventory**

```bash
ls -lh build/distributions/
```

Expected: at least these four files (plus the historical `runtime`-task zip if `org.beryx.runtime` produced one — that's harmless):

```
nocs-0.1.0-SNAPSHOT-linux-arm64.tar.gz
nocs-0.1.0-SNAPSHOT-linux-x86_64.tar.gz
nocs-0.1.0-SNAPSHOT-windows-x86_64.zip
SHA256SUMS.txt
```

- [ ] **Step 11.3: Confirm windows zip launcher behaviour by static inspection**

```bash
unzip -p build/distributions/nocs-0.1.0-SNAPSHOT-windows-x86_64.zip 'nocs-0.1.0-SNAPSHOT/bin/nocs.bat' | grep -c 'NOCS_DATA_DIR'
```

Expected: at least `1` (Task 3's defaulting line is present).

- [ ] **Step 11.4: Update the plan-decomposition status table**

Modify `docs/superpowers/plans/2026-04-22-v0.1-plan-decomposition.md`. In the "Current status" section, change the row

```
| E, G, H, I | No | Author with the `writing-plans` skill when starting that slice |
```

into the two rows

```
| I | Yes | [2026-04-22-nocs-multi-arch-release.md](./2026-04-22-nocs-multi-arch-release.md) |
| E, G, H | No | Author with the `writing-plans` skill when starting that slice |
```

Also flip the **I** row in the "Plan overview (A–I)" table to:

```
| **I** | Multi-arch packaging & release | A | Release archives for linux-arm64 and windows-x86_64 (and polish multi-arch CI); envelope targets from spec §14. Implemented: [2026-04-22-nocs-multi-arch-release.md](./2026-04-22-nocs-multi-arch-release.md). |
```

- [ ] **Step 11.5: Commit and push**

```bash
git add docs/superpowers/plans/2026-04-22-v0.1-plan-decomposition.md
git commit -m "docs: mark Plan I (multi-arch release) as written"
git push
```

After CI goes green on push, tag a test release to exercise the release workflow:

```bash
git tag -a v0.1.0-rc1 -m "release candidate for plan I shakedown"
git push origin v0.1.0-rc1
```

Watch the **Release** workflow in GitHub Actions complete; a draft release titled "NOCS v0.1.0-rc1" should appear under Releases with the three archives and `SHA256SUMS.txt` attached.

---

## Spec cross-reference

| Spec section | Plan I task |
|---|---|
| §14.1 archive layout (`nocs-<version>-<os>-<arch>.<ext>` per OS+arch, `runtime/`, `bin/nocs` or `bin/nocs.bat`, etc.) | Tasks 1, 2, 3 |
| §14.1 envelope (≤150 MB, cold-start ≤15 s on RPi 4, ~400 MB resident) | Task 7 (size); cold-start + memory checked manually before tagging |
| §14.1 "self-contained, no system JRE" | Tasks 1, 2 (Adoptium JDK 25 bundled per platform) |
| §14.2 "tees stdout/stderr into the terminal" | Already in Plan A; not modified |
| §14.3 first-run bootstrap (`%APPDATA%\nocs` on Windows) | Task 3 (launcher default for `NOCS_DATA_DIR`) |
| §1 Goals: "Run on Linux x86_64 and Raspberry Pi 4/5 (arm64)" | Tasks 1, 2, 6, 8 |
| §17 testing/CI | Tasks 4, 5, 6, 8 (multi-platform smoke) |
