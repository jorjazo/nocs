import org.gradle.api.tasks.bundling.Compression
import org.gradle.api.tasks.bundling.Tar

plugins {
    java
    application
    id("org.springframework.boot") version "3.5.3"
    id("io.spring.dependency-management") version "1.1.6"
    id("org.beryx.runtime") version "2.0.1"
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
}

tasks.withType<Test> {
    useJUnitPlatform()
    environment("NOCS_DATA_DIR", layout.buildDirectory.dir("test-data").get().asFile.absolutePath)
}

application {
    mainClass.set("dev.nocs.NocsApplication")
}

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
    imageDir.set(layout.buildDirectory.dir("image").get().asFile)
    imageZip.set(layout.buildDirectory.file("distributions/nocs-${project.version}-linux-x86_64.zip").get().asFile)
}

tasks.register<Tar>("runtimeTarGz") {
    dependsOn("runtime")
    compression = Compression.GZIP
    archiveFileName.set("nocs-${project.version}-linux-x86_64.tar.gz")
    destinationDirectory.set(layout.buildDirectory.dir("distributions"))
    into("nocs-${project.version}") {
        from(layout.buildDirectory.dir("image"))
        filePermissions { unix("755") }
        dirPermissions { unix("755") }
    }
}
