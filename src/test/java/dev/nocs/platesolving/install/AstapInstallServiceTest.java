package dev.nocs.platesolving.install;

import dev.nocs.config.NocsProperties;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import java.net.URI;
import java.nio.file.Path;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.CopyOnWriteArrayList;
import org.awaitility.Awaitility;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import reactor.core.Disposable;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class AstapInstallServiceTest {

    @Test
    void rejectsWhenNetworkDisallowed(@TempDir Path data) {
        AstapInstallService svc = newService(props(false), data, new StubInstaller());

        assertThatThrownBy(() -> svc.start(new InstallRequest(true)))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("allow-network");
    }

    @Test
    void rejectsWhenLicenseNotAccepted(@TempDir Path data) {
        AstapInstallService svc = newService(props(true), data, new StubInstaller());

        assertThatThrownBy(() -> svc.start(new InstallRequest(false)))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("license");
    }

    @Test
    void runsInstallerAndPublishesEvents(@TempDir Path data) {
        EventBus bus = new EventBus();
        List<Event> events = new CopyOnWriteArrayList<>();
        Disposable sub = bus.subscribe(Set.of(Topic.PLATESOLVING)).subscribe(events::add);

        StubInstaller stub = new StubInstaller();
        AstapInstallService svc = new AstapInstallService(
                props(true), data, bus, stub, p -> java.util.Optional.of(SPEC));

        svc.start(new InstallRequest(true));

        Awaitility.await().atMost(Duration.ofSeconds(5))
                .until(() -> svc.progress().phase() == InstallPhase.DONE);

        assertThat(stub.invoked).isTrue();
        assertThat(events).extracting(Event::type)
                .contains("install_started", "install_completed");
        sub.dispose();
    }

    private static NocsProperties props(boolean allowNetwork) {
        NocsProperties.PlateSolving.Astap astap = new NocsProperties.PlateSolving.Astap("", "", "H18");
        NocsProperties.PlateSolving.Install install = new NocsProperties.PlateSolving.Install(
                allowNetwork, "https://example.invalid/{os}-{arch}.zip",
                Map.of("linux-x86_64", "deadbeef"),
                "https://example.invalid/h18.zip", "cafebabe");
        NocsProperties.PlateSolving ps = new NocsProperties.PlateSolving("astap", 60L, astap, install);
        return new NocsProperties(null, null, null, null, null, null, null, ps);
    }

    private static AstapInstallService newService(
            NocsProperties props, Path data, AstapInstaller installer) {
        return new AstapInstallService(props, data, new EventBus(), installer, p -> java.util.Optional.of(SPEC));
    }

    private static final AstapInstallSpec SPEC = new AstapInstallSpec(
            URI.create("file:/tmp/binary.zip"), "deadbeef", ArchiveKind.ZIP, "astap_cli",
            URI.create("file:/tmp/db.zip"), "cafebabe", "H18", ArchiveKind.ZIP);

    private static class StubInstaller extends AstapInstaller {
        boolean invoked;

        StubInstaller() {
            super((url, dest, listener) -> {}, new Sha256Verifier(), new ZipExtractor(), new TarGzExtractor());
        }

        @Override
        public Path install(AstapInstallSpec spec, Path dataDir, InstallEvents events) {
            invoked = true;
            events.phase(InstallPhase.DOWNLOADING_BINARY, "x");
            events.bytes(InstallPhase.DOWNLOADING_BINARY, 50L, 100L);
            events.phase(InstallPhase.DONE, "x");
            return dataDir.resolve("astap/bin/astap_cli");
        }
    }
}
