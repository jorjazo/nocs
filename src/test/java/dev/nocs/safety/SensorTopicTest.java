package dev.nocs.safety;

import dev.nocs.events.Topic;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class SensorTopicTest {

    @Test
    void sensorTopicExists() {
        assertThat(Topic.valueOf("SENSOR")).isEqualTo(Topic.SENSOR);
        assertThat(Topic.SENSOR.wire()).isEqualTo("sensor");
        assertThat(Topic.fromWire("sensor")).isEqualTo(Topic.SENSOR);
    }
}
