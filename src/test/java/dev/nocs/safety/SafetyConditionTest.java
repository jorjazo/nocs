package dev.nocs.safety;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class SafetyConditionTest {

    @Test
    void recordsCarryTheirParameters() {
        assertThat(new SafetyCondition.HumidityAbove(85).percent()).isEqualTo(85.0);
        assertThat(new SafetyCondition.RainDetected()).isInstanceOf(SafetyCondition.class);
        assertThat(new SafetyCondition.AltitudeBelow(20).degrees()).isEqualTo(20.0);
        assertThat(new SafetyCondition.SensorOffline("weather", 120).sensor()).isEqualTo("weather");
        assertThat(new SafetyCondition.SensorOffline("weather", 120).thresholdSeconds()).isEqualTo(120L);
    }

    @Test
    void wireNamesAreStable() {
        assertThat(SafetyCondition.wireOf(new SafetyCondition.HumidityAbove(85))).isEqualTo("humidity_above");
        assertThat(SafetyCondition.wireOf(new SafetyCondition.RainDetected())).isEqualTo("rain_detected");
        assertThat(SafetyCondition.wireOf(new SafetyCondition.AltitudeBelow(20))).isEqualTo("altitude_below");
        assertThat(SafetyCondition.wireOf(new SafetyCondition.SensorOffline("weather", 1)))
                .isEqualTo("sensor_offline");
    }
}
