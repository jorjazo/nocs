package dev.nocs.target.catalog;

import dev.nocs.target.Target;
import dev.nocs.target.TargetKind;
import java.util.List;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class InMemoryTargetIndexTest {

    private Target t(String id, String name, List<String> aliases) {
        return new Target(id, name, aliases, TargetKind.GALAXY, 10.0, 20.0, "And", 3.0, 100, "");
    }

    @Test
    void exactAliasMatchBeatsSubstring() {
        InMemoryTargetIndex idx = new InMemoryTargetIndex(List.of(
                t("a:1", "Apple", List.of()),
                t("a:2", "Pineapple", List.of("Apple pie")),
                t("a:3", "Apple Pi", List.of("Apple"))));
        List<Target> hits = idx.search("apple", 10);
        assertThat(hits).isNotEmpty();
        assertThat(hits.get(0).id()).isEqualTo("a:1");
    }

    @Test
    void emptyQueryReturnsEmpty() {
        InMemoryTargetIndex idx = new InMemoryTargetIndex(List.of(t("a:1", "x", List.of())));
        assertThat(idx.search("", 10)).isEmpty();
    }

    @Test
    void findByIdReturnsTarget() {
        Target tx = t("messier:M31", "M31", List.of("Andromeda"));
        InMemoryTargetIndex idx = new InMemoryTargetIndex(List.of(tx));
        assertThat(idx.findById("messier:M31")).contains(tx);
        assertThat(idx.findById("messier:M999")).isEmpty();
    }

    @Test
    void searchMatchesAliasCaseInsensitive() {
        Target tx = t("messier:M31", "M31", List.of("Andromeda Galaxy", "NGC 224"));
        InMemoryTargetIndex idx = new InMemoryTargetIndex(List.of(tx));
        assertThat(idx.search("ANDROMEDA", 10)).contains(tx);
        assertThat(idx.search("ngc 224", 10)).contains(tx);
    }
}
