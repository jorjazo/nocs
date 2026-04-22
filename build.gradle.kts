plugins {
    java
    application
    id("org.springframework.boot") version "3.5.3"
    id("io.spring.dependency-management") version "1.1.6"
    id("org.beryx.runtime") version "2.0.1"
}

extra["flyway.version"] = "12.4.0"

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
    implementation("org.flywaydb:flyway-database-nc-sqlite:12.4.0")
    implementation("com.fasterxml.jackson.dataformat:jackson-dataformat-yaml")

    testImplementation("org.springframework.boot:spring-boot-starter-test")
    testImplementation("org.springframework.security:spring-security-test")
    testImplementation("io.projectreactor:reactor-test")
}

tasks.withType<Test> {
    useJUnitPlatform()
}

application {
    mainClass.set("dev.nocs.NocsApplication")
}
