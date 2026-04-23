package dev.nocs.safety;

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
            "nocs.safety.rules-path=/tmp/nocs-safety-test.yaml",
            "nocs.safety.altitude-eval-interval-ms=2500",
            "nocs.safety.sensor-offline-default-seconds=42"
        })
class SafetyConfigTest {

    @Autowired
    NocsProperties props;

    @Test
    void bindsSafetySection() {
        assertThat(props.safety()).isNotNull();
        assertThat(props.safety().rulesPath()).isEqualTo("/tmp/nocs-safety-test.yaml");
        assertThat(props.safety().altitudeEvalIntervalMs()).isEqualTo(2500L);
        assertThat(props.safety().sensorOfflineDefaultSeconds()).isEqualTo(42L);
    }

    @Test
    void defaultsAreApplied() {
        NocsProperties.Safety s = new NocsProperties.Safety(null, null, null);
        assertThat(s.rulesPath()).isNull();
        assertThat(s.altitudeEvalIntervalMs()).isEqualTo(10_000L);
        assertThat(s.sensorOfflineDefaultSeconds()).isEqualTo(60L);
    }
}
