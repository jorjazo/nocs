package dev.nocs.target;

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
            "nocs.targets.online-resolver=true",
            "nocs.targets.simbad-base-url=https://example.invalid/simbad"
        })
class TargetsConfigTest {

    @Autowired
    NocsProperties props;

    @Test
    void bindsTargetsSection() {
        assertThat(props.targets()).isNotNull();
        assertThat(props.targets().onlineResolver()).isTrue();
        assertThat(props.targets().simbadBaseUrl())
                .isEqualTo("https://example.invalid/simbad");
    }
}
