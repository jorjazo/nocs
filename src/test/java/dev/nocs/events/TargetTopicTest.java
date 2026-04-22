package dev.nocs.events;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class TargetTopicTest {

    @Test
    void targetTopicExists() {
        assertThat(Topic.valueOf("TARGET")).isEqualTo(Topic.TARGET);
        assertThat(Topic.TARGET.wire()).isEqualTo("target");
        assertThat(Topic.fromWire("target")).isEqualTo(Topic.TARGET);
    }
}
