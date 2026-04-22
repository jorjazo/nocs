package dev.nocs.target.catalog;

import dev.nocs.target.Target;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class SolarSystemCatalogTest {

    @Test
    void listsAllTenBodies() {
        List<Target> all = SolarSystemCatalog.staticTargets();
        assertThat(all).extracting(Target::id).contains(
                "sun", "moon",
                "planet:mercury", "planet:venus", "planet:mars",
                "planet:jupiter", "planet:saturn", "planet:uranus",
                "planet:neptune", "planet:pluto");
    }

    @Test
    void resolveSunGivesLiveCoordinates() {
        Optional<Target> t = SolarSystemCatalog.resolveWithPosition("sun", Instant.parse("2026-03-20T14:46:00Z"));
        assertThat(t).isPresent();
        assertThat(t.get().raJ2000Deg()).isBetween(0.0, 360.0);
        assertThat(t.get().decJ2000Deg()).isBetween(-1.0, 1.0);
    }

    @Test
    void resolveUnknownReturnsEmpty() {
        assertThat(SolarSystemCatalog.resolveWithPosition("planet:nibiru", Instant.now())).isEmpty();
    }

    @Test
    void searchMatchesSun() {
        assertThat(SolarSystemCatalog.search("sun", Instant.now(), 5)).extracting(Target::id).contains("sun");
    }
}
