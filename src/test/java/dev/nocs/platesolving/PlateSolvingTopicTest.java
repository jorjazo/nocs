package dev.nocs.platesolving;

import dev.nocs.events.Topic;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class PlateSolvingTopicTest {

    @Test
    void platesolvingTopicExists() {
        assertThat(Topic.valueOf("PLATESOLVING")).isEqualTo(Topic.PLATESOLVING);
        assertThat(Topic.PLATESOLVING.wire()).isEqualTo("platesolving");
        assertThat(Topic.fromWire("platesolving")).isEqualTo(Topic.PLATESOLVING);
    }
}
