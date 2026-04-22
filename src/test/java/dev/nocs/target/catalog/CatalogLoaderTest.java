package dev.nocs.target.catalog;

import dev.nocs.target.Target;
import java.io.InputStream;
import java.util.List;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class CatalogLoaderTest {

    @Test
    void parsesMiniFixture() throws Exception {
        InputStream in = getClass().getResourceAsStream("/catalogs/mini-messier.tsv");
        assertThat(in).as("fixture must be on classpath").isNotNull();
        List<Target> targets = CatalogLoader.readTsv(in);
        assertThat(targets).hasSize(3);
        Target m31 = targets.stream().filter(t -> t.id().equals("messier:M31")).findFirst().orElseThrow();
        assertThat(m31.primaryName()).isEqualTo("M31");
        assertThat(m31.aliases()).contains("NGC224", "Andromeda Galaxy");
        assertThat(m31.raJ2000Deg()).isCloseTo(10.684708, org.assertj.core.data.Offset.offset(1e-6));
    }
}
