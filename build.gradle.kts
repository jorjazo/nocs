import org.gradle.api.tasks.Exec
import org.gradle.api.tasks.Sync
import org.gradle.api.tasks.bundling.Zip

plugins {
    java
    application
    id("org.springframework.boot") version "3.5.3"
    id("io.spring.dependency-management") version "1.1.6"
    id("org.beryx.runtime") version "2.0.1"
    id("com.github.node-gradle.node") version "7.1.0"
}

group = "dev.nocs"
version = "0.1.0-SNAPSHOT"

java {
    toolchain {
        languageVersion.set(JavaLanguageVersion.of(25))
    }
}

repositories {
    mavenCentral()
}

dependencies {
    implementation("org.springframework.boot:spring-boot-starter-web")
    implementation("org.springframework.boot:spring-boot-starter-security")
    implementation("org.springframework.boot:spring-boot-starter-jdbc")
    implementation("io.projectreactor:reactor-core")
    implementation("org.xerial:sqlite-jdbc:3.49.1.0")
    implementation("org.flywaydb:flyway-core")
    implementation("com.fasterxml.jackson.dataformat:jackson-dataformat-yaml")

    testImplementation("org.springframework.boot:spring-boot-starter-test")
    testImplementation("org.springframework.security:spring-security-test")
    testImplementation("io.projectreactor:reactor-test")
    testImplementation("org.springframework:spring-webflux")
    testImplementation("io.projectreactor.netty:reactor-netty-http")
    testImplementation("org.awaitility:awaitility:4.2.2")
}

tasks.withType<Test> {
    useJUnitPlatform()
    environment("NOCS_DATA_DIR", layout.buildDirectory.dir("test-data").get().asFile.absolutePath)
}

application {
    mainClass.set("dev.nocs.NocsApplication")
}

/** Host OS/arch must match the chosen target: badass-runtime always invokes the *build* JDK's jlink. */
fun detectPackagingTarget(): String {
    val os = System.getProperty("os.name").lowercase()
    val arch = System.getProperty("os.arch").lowercase()
    return when {
        os.contains("windows") -> "windows-x86_64"
        os.contains("mac") || os.contains("darwin") ->
            throw GradleException(
                "macOS is not a v0.1 packaging host. Set -Pnocs.packaging.target to linux-x86_64, " +
                    "linux-arm64, or windows-x86_64 and run on a matching CI runner.",
            )
        os.contains("linux") && (arch == "aarch64" || arch == "arm64") -> "linux-arm64"
        os.contains("linux") -> "linux-x86_64"
        else -> throw GradleException("Unsupported host for packaging: os=$os arch=$arch")
    }
}

val packagingTarget: org.gradle.api.provider.Provider<String> =
    providers
        .gradleProperty("nocs.packaging.target")
        .map { it.trim().lowercase() }
        .orElse(provider { detectPackagingTarget() })

val jdk25Version = "25.0.2"
val jdk25Build = "10"
val jdk25Tag = "jdk-${jdk25Version}%2B${jdk25Build}"
val jdk25Base = "https://github.com/adoptium/temurin25-binaries/releases/download/${jdk25Tag}"

val jdkUrls =
    mapOf(
        "linux-x86_64" to "${jdk25Base}/OpenJDK25U-jdk_x64_linux_hotspot_${jdk25Version}_${jdk25Build}.tar.gz",
        "linux-arm64" to "${jdk25Base}/OpenJDK25U-jdk_aarch64_linux_hotspot_${jdk25Version}_${jdk25Build}.tar.gz",
        "windows-x86_64" to "${jdk25Base}/OpenJDK25U-jdk_x64_windows_hotspot_${jdk25Version}_${jdk25Build}.zip",
    )

runtime {
    options.set(listOf("--strip-debug", "--compress", "2", "--no-header-files", "--no-man-pages"))
    modules.set(
        listOf(
            "java.base",
            "java.desktop",
            "java.instrument",
            "java.logging",
            "java.management",
            "java.naming",
            "java.net.http",
            "java.prefs",
            "java.security.jgss",
            "java.sql",
            "java.xml",
            "jdk.crypto.ec",
            "jdk.jdi",
            "jdk.unsupported",
        ),
    )
    imageDir.set(layout.buildDirectory.dir("image/nocs").get().asFile)

    when (packagingTarget.get()) {
        "linux-x86_64" ->
            targetPlatform("linux-x86_64") {
                setJdkHome(jdkDownload(jdkUrls["linux-x86_64"]!!))
            }
        "linux-arm64" ->
            targetPlatform("linux-arm64") {
                setJdkHome(jdkDownload(jdkUrls["linux-arm64"]!!))
            }
        "windows-x86_64" ->
            targetPlatform("windows-x86_64") {
                setJdkHome(jdkDownload(jdkUrls["windows-x86_64"]!!))
            }
        else ->
            throw GradleException(
                "Unknown nocs.packaging.target '${packagingTarget.get()}'. " +
                    "Use linux-x86_64, linux-arm64, or windows-x86_64.",
            )
    }
}

fun imageRootForTarget(target: String) = layout.buildDirectory.dir("image/nocs/nocs-$target")

val syncLinuxX64Image =
    tasks.register<Sync>("syncLinuxX64Image") {
        group = "distribution"
        description = "Stage linux-x86_64 jlink tree for tarball (preserves executable bits)."
        onlyIf { packagingTarget.get() == "linux-x86_64" }
        dependsOn("runtime")
        from(imageRootForTarget("linux-x86_64")) {
            exclude("bin/nocs.bat")
        }
        into(layout.buildDirectory.dir("tmp/tar-staging-linux-x86_64/nocs-${project.version}"))
    }

tasks.register<Exec>("runtimeTarLinuxX64") {
    group = "distribution"
    description = "Build the linux-x86_64 self-contained tar.gz (host must be linux x86_64)."
    onlyIf { packagingTarget.get() == "linux-x86_64" }
    dependsOn(syncLinuxX64Image)
    val archive = layout.buildDirectory.file("distributions/nocs-${project.version}-linux-x86_64.tar.gz")
    val stagingParent = layout.buildDirectory.dir("tmp/tar-staging-linux-x86_64").get().asFile
    workingDir(stagingParent)
    doFirst { archive.get().asFile.parentFile.mkdirs() }
    commandLine(
        "tar",
        "-czf",
        archive.get().asFile.absolutePath,
        "nocs-${project.version}",
    )
    outputs.file(archive)
}

val syncLinuxArm64Image =
    tasks.register<Sync>("syncLinuxArm64Image") {
        group = "distribution"
        description = "Stage linux-arm64 jlink tree for tarball (preserves executable bits)."
        onlyIf { packagingTarget.get() == "linux-arm64" }
        dependsOn("runtime")
        from(imageRootForTarget("linux-arm64")) {
            exclude("bin/nocs.bat")
        }
        into(layout.buildDirectory.dir("tmp/tar-staging-linux-arm64/nocs-${project.version}"))
    }

tasks.register<Exec>("runtimeTarLinuxArm64") {
    group = "distribution"
    description = "Build the linux-arm64 self-contained tar.gz (host must be linux arm64)."
    onlyIf { packagingTarget.get() == "linux-arm64" }
    dependsOn(syncLinuxArm64Image)
    val archive = layout.buildDirectory.file("distributions/nocs-${project.version}-linux-arm64.tar.gz")
    val stagingParent = layout.buildDirectory.dir("tmp/tar-staging-linux-arm64").get().asFile
    workingDir(stagingParent)
    doFirst { archive.get().asFile.parentFile.mkdirs() }
    commandLine(
        "tar",
        "-czf",
        archive.get().asFile.absolutePath,
        "nocs-${project.version}",
    )
    outputs.file(archive)
}

tasks.register("patchWindowsLauncher") {
    group = "distribution"
    description = "Inject NOCS_DATA_DIR default into generated bin/nocs.bat (Windows images only)."
    onlyIf { packagingTarget.get() == "windows-x86_64" }
    dependsOn("runtime")
    val launcher = layout.buildDirectory.file("image/nocs/nocs-windows-x86_64/bin/nocs.bat")
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
        val anchor =
            Regex("""(?m)^for %%i in \("%APP_HOME%"\) do set APP_HOME=%%~fi\s*$""")
        val match =
            anchor.find(original)
                ?: throw GradleException(
                    "Could not find APP_HOME anchor in nocs.bat — Gradle's windows template changed.",
                )
        val injection =
            buildString {
                append(System.lineSeparator())
                append("@rem ${marker}: default NOCS data dir if the user did not set one.")
                append(System.lineSeparator())
                append("if not defined NOCS_DATA_DIR set \"NOCS_DATA_DIR=%APPDATA%\\nocs\"")
                append(System.lineSeparator())
            }
        val patched =
            original.substring(0, match.range.last + 1) +
                injection +
                original.substring(match.range.last + 1)
        file.writeText(patched, Charsets.ISO_8859_1)
        logger.lifecycle("Patched ${file.name} with NOCS_DATA_DIR default.")
    }
}

tasks.register<Zip>("runtimeZipWindowsX64") {
    group = "distribution"
    description = "Build the windows-x86_64 self-contained zip (host must be Windows x86_64)."
    onlyIf { packagingTarget.get() == "windows-x86_64" }
    dependsOn("runtime", "patchWindowsLauncher")
    archiveFileName.set("nocs-${project.version}-windows-x86_64.zip")
    destinationDirectory.set(layout.buildDirectory.dir("distributions"))
    into("nocs-${project.version}") {
        from(imageRootForTarget("windows-x86_64")) {
            exclude("bin/nocs")
        }
    }
}

tasks.register("runtimeDist") {
    group = "distribution"
    description =
        "Build the release archive for nocs.packaging.target (or auto-detected host). " +
            "Foreign architectures require a matching CI runner."
    when (packagingTarget.get()) {
        "linux-x86_64" -> dependsOn("runtimeTarLinuxX64")
        "linux-arm64" -> dependsOn("runtimeTarLinuxArm64")
        "windows-x86_64" -> dependsOn("runtimeZipWindowsX64")
        else -> throw GradleException("Unknown packaging target: ${packagingTarget.get()}")
    }
}

tasks.register("runtimeAll") {
    group = "distribution"
    description =
        "Alias for runtimeDist. Builds one archive for *this* runner's target only; " +
            "full multi-arch needs CI matrix jobs."
    dependsOn("runtimeDist")
}

tasks.register("runtimeTarGz") {
    group = "distribution"
    description = "Deprecated. Alias for runtimeDist."
    dependsOn("runtimeDist")
    doFirst {
        logger.warn(
            "Task ':runtimeTarGz' is deprecated; use ':runtimeDist' or the platform-specific task.",
        )
    }
}

val maxArchiveBytes = 150L * 1024L * 1024L

tasks.register("verifyArchiveSize") {
    group = "verification"
    description = "Fail if the release archive for this target exceeds the spec §14.1 envelope (150 MB)."
    dependsOn("runtimeDist")
    doLast {
        val dir = layout.buildDirectory.dir("distributions").get().asFile
        val name =
            when (packagingTarget.get()) {
                "linux-x86_64" -> "nocs-${project.version}-linux-x86_64.tar.gz"
                "linux-arm64" -> "nocs-${project.version}-linux-arm64.tar.gz"
                "windows-x86_64" -> "nocs-${project.version}-windows-x86_64.zip"
                else -> throw GradleException("Unknown packaging target: ${packagingTarget.get()}")
            }
        val f = dir.resolve(name)
        if (!f.exists()) {
            throw GradleException("Archive missing: ${f.absolutePath}")
        }
        val sizeMb = f.length().toDouble() / (1024.0 * 1024.0)
        logger.lifecycle(String.format("%-50s %6.1f MB", f.name, sizeMb))
        if (f.length() > maxArchiveBytes) {
            throw GradleException(
                String.format("%s exceeds 150 MB envelope (%.1f MB)", f.name, sizeMb),
            )
        }
        val webDir = layout.buildDirectory.dir("generated/nocs-spa/static").get().asFile
        if (webDir.exists()) {
            val webBytes = webDir.walkTopDown().filter { it.isFile }.sumOf { it.length() }
            val webMb = webBytes.toDouble() / (1024.0 * 1024.0)
            logger.lifecycle(String.format("%-50s %6.1f MB (web/dist)", "web bundle", webMb))
            if (webBytes > 8L * 1024 * 1024) {
                logger.warn(
                    "Web bundle exceeds 8 MB — investigate Vite build output (vite-bundle-visualizer).",
                )
            }
        }
    }
}

// --- Web client (Vite + React) — see docs/superpowers/plans/2026-04-23-nocs-web-client.md (Task 1)
node {
    version.set("22.12.0")
    npmVersion.set("10.9.0")
    download.set(true)
    workDir.set(layout.buildDirectory.dir("nodejs"))
    npmWorkDir.set(layout.buildDirectory.dir("npm"))
    nodeProjectDir.set(file("web"))
}

// Vite output must land under `static/` so ResourceHttpRequestHandler maps `classpath:/static/`.
val webSpaResourceRoot = layout.buildDirectory.dir("generated/nocs-spa")

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
        description = "Copy web/dist into generated/nocs-spa/static for classpath:/static/."
        dependsOn(npmBuildWeb)
        from("web/dist")
        into(webSpaResourceRoot.map { it.dir("static") })
    }

sourceSets.named("main") {
    resources.srcDir(webSpaResourceRoot)
}

tasks.named("processResources") {
    dependsOn(syncWebDist)
}

val npmTestWeb =
    tasks.register<com.github.gradle.node.npm.task.NpmTask>("npmTestWeb") {
        group = "verification"
        description = "Run web/ Vitest suite."
        dependsOn(npmCiWeb)
        args.set(listOf("test"))
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
