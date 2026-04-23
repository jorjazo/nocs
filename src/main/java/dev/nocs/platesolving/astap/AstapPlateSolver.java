package dev.nocs.platesolving.astap;

import dev.nocs.config.NocsProperties;
import dev.nocs.platesolving.FailureKind;
import dev.nocs.platesolving.PlateSolvingService;
import dev.nocs.platesolving.SolveOptions;
import dev.nocs.platesolving.SolveOutcome;
import java.nio.file.Path;
import java.util.Optional;

public class AstapPlateSolver implements PlateSolvingService {

    private final AstapInstallationLocator locator;
    private final AstapInvoker invoker;
    private final NocsProperties props;
    private final Path dataDir;

    public AstapPlateSolver(
            AstapInstallationLocator locator, AstapInvoker invoker, NocsProperties props, Path dataDir) {
        this.locator = locator;
        this.invoker = invoker;
        this.props = props;
        this.dataDir = dataDir;
    }

    @Override
    public SolveOutcome solve(byte[] fits, SolveOptions options) {
        Optional<AstapInstallation> installed = locator.locate(props, dataDir);
        if (installed.isEmpty()) {
            return new SolveOutcome.Failed(
                    FailureKind.NOT_INSTALLED,
                    "ASTAP not installed; POST /api/platesolving/install or set "
                            + "nocs.platesolving.astap.binary-path",
                    0L);
        }
        long timeout = effectiveTimeout(options);
        return invoker.invoke(installed.get(), fits, options, timeout);
    }

    @Override
    public boolean isAvailable() {
        return locator.locate(props, dataDir).isPresent();
    }

    private long effectiveTimeout(SolveOptions options) {
        if (options.timeoutSec() != null) {
            return Math.max(1L, options.timeoutSec().longValue());
        }
        long fromConfig = props.platesolving() == null ? 60L : props.platesolving().solveTimeoutSec();
        return Math.max(1L, fromConfig);
    }
}
