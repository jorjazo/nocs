package dev.nocs.platesolving.install;

import dev.nocs.config.NocsProperties;
import java.net.URI;
import java.util.Locale;
import java.util.Optional;

public final class AstapInstallSpecs {

    private AstapInstallSpecs() {}

    public static Optional<AstapInstallSpec> forCurrent(NocsProperties props) {
        return forPlatform(props, currentPlatformKey());
    }

    public static Optional<AstapInstallSpec> forPlatform(NocsProperties props, String platformKey) {
        if (platformKey == null) {
            return Optional.empty();
        }
        if (props.platesolving() == null) {
            return Optional.empty();
        }
        NocsProperties.PlateSolving.Install install = props.platesolving().install();
        if (install == null) {
            return Optional.empty();
        }
        String urlTpl = install.binaryUrlTemplate();
        String binarySha = install.binarySha256().get(platformKey);
        String dbUrl = install.dbUrl();
        String dbSha = install.dbSha256();
        if (urlTpl == null || urlTpl.isBlank() || binarySha == null || binarySha.isBlank()
                || dbUrl == null || dbUrl.isBlank() || dbSha == null || dbSha.isBlank()) {
            return Optional.empty();
        }
        String[] parts = platformKey.split("-", 2);
        String os = parts.length > 0 ? parts[0] : "";
        String arch = parts.length > 1 ? parts[1] : "";
        URI binary = URI.create(urlTpl.replace("{os}", os).replace("{arch}", arch));
        URI db = URI.create(dbUrl);
        ArchiveKind binaryKind = "windows".equals(os) ? ArchiveKind.ZIP : ArchiveKind.TAR_GZ;
        return Optional.of(new AstapInstallSpec(
                binary, binarySha, binaryKind, defaultBinaryEntry(os), db, dbSha,
                props.platesolving().astap().dbName(), ArchiveKind.ZIP));
    }

    public static String currentPlatformKey() {
        String os = System.getProperty("os.name", "").toLowerCase(Locale.ROOT);
        String arch = System.getProperty("os.arch", "").toLowerCase(Locale.ROOT);
        String osKey;
        if (os.contains("win")) {
            osKey = "windows";
        } else if (os.contains("mac") || os.contains("darwin")) {
            return null;
        } else {
            osKey = "linux";
        }
        String archKey;
        if (arch.contains("aarch64") || arch.contains("arm64")) {
            archKey = "arm64";
        } else if (arch.contains("amd64") || arch.contains("x86_64")) {
            archKey = "x86_64";
        } else {
            return null;
        }
        return osKey + "-" + archKey;
    }

    private static String defaultBinaryEntry(String os) {
        return "windows".equals(os) ? "astap_cli.exe" : "astap_cli";
    }
}
