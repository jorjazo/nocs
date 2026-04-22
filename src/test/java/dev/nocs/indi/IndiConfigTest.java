package dev.nocs.indi;

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
            "nocs.indi.mode=external",
            "nocs.indi.host=127.0.0.1",
            "nocs.indi.port=7624",
            "nocs.indi.drivers[0]=indi_simulator_telescope",
            "nocs.indi.drivers[1]=indi_simulator_ccd",
            "nocs.indi.restart.initial-backoff-ms=200",
            "nocs.indi.restart.max-backoff-ms=5000",
        })
class IndiConfigTest {

    @Autowired
    NocsProperties props;

    @Test
    void bindsIndiSection() {
        IndiConfig indi = props.indi();
        assertThat(indi).isNotNull();
        assertThat(indi.mode()).isEqualTo(IndiConfig.Mode.EXTERNAL);
        assertThat(indi.host()).isEqualTo("127.0.0.1");
        assertThat(indi.port()).isEqualTo(7624);
        assertThat(indi.drivers())
                .containsExactly("indi_simulator_telescope", "indi_simulator_ccd");
        assertThat(indi.restart().initialBackoffMs()).isEqualTo(200);
        assertThat(indi.restart().maxBackoffMs()).isEqualTo(5000);
    }
}
