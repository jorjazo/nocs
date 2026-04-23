package dev.nocs.platesolving.astap;

import dev.nocs.platesolving.SolveOptions;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.List;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class AstapInvocationTest {

    @Test
    void minimalCommandIncludesBinaryFitsAndDb() {
        AstapInstallation inst = new AstapInstallation(
                Paths.get("/opt/astap/astap_cli"), Paths.get("/srv/db"), "H18");

        List<String> cmd = AstapInvocation.command(inst, Path.of("/tmp/sub.fits"), SolveOptions.defaults());

        assertThat(cmd).containsSequence("/opt/astap/astap_cli", "-f", "/tmp/sub.fits");
        assertThat(cmd).containsSequence("-d", "/srv/db");
        assertThat(cmd).contains("-wcs");
    }

    @Test
    void hintsAreAppendedWhenProvided() {
        AstapInstallation inst = new AstapInstallation(
                Paths.get("astap_cli"), Paths.get("db"), "H18");
        SolveOptions opts = new SolveOptions(160.0, 41.0, 5.0, null, null);

        List<String> cmd = AstapInvocation.command(inst, Path.of("sub.fits"), opts);

        assertThat(cmd).containsSequence("-ra", "10.6666666667");
        assertThat(cmd).containsSequence("-spd", "131.0");
        assertThat(cmd).containsSequence("-r", "5.0");
        assertThat(cmd).doesNotContain("-fov");
    }
}
