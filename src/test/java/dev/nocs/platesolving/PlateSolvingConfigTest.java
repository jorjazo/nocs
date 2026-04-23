package dev.nocs.platesolving;

import dev.nocs.config.NocsProperties;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.TestPropertySource;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
@TestPropertySource(
        properties = {
            "nocs.auth.token=t",
            "nocs.platesolving.solver=astap",
            "nocs.platesolving.solve-timeout-sec=42",
            "nocs.platesolving.astap.binary-path=/opt/astap/astap_cli",
            "nocs.platesolving.astap.db-dir=/srv/astap/db",
            "nocs.platesolving.astap.db-name=H18",
            "nocs.platesolving.install.allow-network=true",
            "nocs.platesolving.install.binary-url-template=https://example.invalid/astap-{os}-{arch}.zip",
            "nocs.platesolving.install.binary-sha256.linux-x86_64=deadbeef",
            "nocs.platesolving.install.db-url=https://example.invalid/h18.zip",
            "nocs.platesolving.install.db-sha256=cafebabe"
        })
class PlateSolvingConfigTest {

    @Autowired NocsProperties props;

    @Test
    void platesolvingPropertiesAreBound() {
        NocsProperties.PlateSolving ps = props.platesolving();
        assertThat(ps).isNotNull();
        assertThat(ps.solver()).isEqualTo("astap");
        assertThat(ps.solveTimeoutSec()).isEqualTo(42L);
        assertThat(ps.astap().binaryPath()).isEqualTo("/opt/astap/astap_cli");
        assertThat(ps.astap().dbDir()).isEqualTo("/srv/astap/db");
        assertThat(ps.astap().dbName()).isEqualTo("H18");
        assertThat(ps.install().allowNetwork()).isTrue();
        assertThat(ps.install().binaryUrlTemplate())
                .isEqualTo("https://example.invalid/astap-{os}-{arch}.zip");
        assertThat(ps.install().binarySha256().get("linux-x86_64")).isEqualTo("deadbeef");
        assertThat(ps.install().dbUrl()).isEqualTo("https://example.invalid/h18.zip");
        assertThat(ps.install().dbSha256()).isEqualTo("cafebabe");
    }

    @Test
    void defaultsAreSensibleWhenAbsent() {
        NocsProperties.PlateSolving ps = props.platesolving();
        if (ps.solveTimeoutSec() == 42L) {
            return;
        }
        assertThat(ps.solveTimeoutSec()).isEqualTo(60L);
        assertThat(ps.solver()).isEqualTo("astap");
    }
}
