package dev.nocs.platesolving.install;

import dev.nocs.config.NocsProperties;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class AstapInstallSpecsTest {

    @Test
    void resolvesLinuxX86_64WhenConfigured() {
        NocsProperties props = props("https://example.invalid/astap-{os}-{arch}.tar.gz",
                Map.of("linux-x86_64", "deadbeef"),
                "https://example.invalid/h18.zip", "cafebabe");

        Optional<AstapInstallSpec> out = AstapInstallSpecs.forPlatform(props, "linux-x86_64");

        assertThat(out).isPresent();
        AstapInstallSpec spec = out.get();
        assertThat(spec.binaryUrl().toString()).isEqualTo("https://example.invalid/astap-linux-x86_64.tar.gz");
        assertThat(spec.binarySha256()).isEqualTo("deadbeef");
        assertThat(spec.binaryKind()).isEqualTo(ArchiveKind.TAR_GZ);
        assertThat(spec.binaryEntryName()).isEqualTo("astap_cli");
        assertThat(spec.dbUrl().toString()).isEqualTo("https://example.invalid/h18.zip");
    }

    @Test
    void resolvesWindowsX86_64Zip() {
        NocsProperties props = props("https://example.invalid/{os}-{arch}.zip",
                Map.of("windows-x86_64", "abc"), "https://example.invalid/h18.zip", "def");

        Optional<AstapInstallSpec> out = AstapInstallSpecs.forPlatform(props, "windows-x86_64");

        assertThat(out).isPresent();
        assertThat(out.get().binaryKind()).isEqualTo(ArchiveKind.ZIP);
        assertThat(out.get().binaryEntryName()).isEqualTo("astap_cli.exe");
    }

    @Test
    void unsupportedPlatformReturnsEmpty() {
        NocsProperties props = props("https://example.invalid/{os}-{arch}.zip",
                Map.of("linux-x86_64", "abc"), "https://example.invalid/h18.zip", "def");

        assertThat(AstapInstallSpecs.forPlatform(props, "linux-arm64")).isEmpty();
    }

    @Test
    void blankConfigReturnsEmpty() {
        NocsProperties props = props("", Map.of(), "", "");
        assertThat(AstapInstallSpecs.forPlatform(props, "linux-x86_64")).isEmpty();
    }

    private static NocsProperties props(String tpl, Map<String, String> binSha, String dbUrl, String dbSha) {
        NocsProperties.PlateSolving.Astap astap = new NocsProperties.PlateSolving.Astap("", "", "H18");
        NocsProperties.PlateSolving.Install install = new NocsProperties.PlateSolving.Install(
                true, tpl, binSha, dbUrl, dbSha);
        NocsProperties.PlateSolving ps = new NocsProperties.PlateSolving("astap", 60L, astap, install);
        return new NocsProperties(null, null, null, null, null, null, null, ps);
    }
}
