package dev.nocs.config;

import dev.nocs.bootstrap.DataDirBootstrap;
import dev.nocs.device.CameraImageSink;
import dev.nocs.device.DeviceService;
import dev.nocs.events.EventBus;
import dev.nocs.image.ImageStoreService;
import dev.nocs.platesolving.DisabledPlateSolvingService;
import dev.nocs.platesolving.PlateSolvingService;
import dev.nocs.platesolving.astap.AstapInstallationLocator;
import dev.nocs.platesolving.astap.AstapInvoker;
import dev.nocs.platesolving.astap.AstapPlateSolver;
import dev.nocs.platesolving.install.AstapInstallService;
import dev.nocs.platesolving.install.AstapInstallSpecs;
import dev.nocs.platesolving.install.AstapInstaller;
import dev.nocs.observatory.ObservatoryService;
import dev.nocs.safety.SafetyActionDispatcher;
import dev.nocs.safety.SafetyRuleEngine;
import dev.nocs.safety.SafetyRuleParser;
import dev.nocs.safety.SafetyService;
import dev.nocs.safety.SafetyState;
import dev.nocs.safety.SessionLogSink;
import dev.nocs.session.SessionService;
import dev.nocs.indi.IndiClient;
import dev.nocs.indi.IndiConfig;
import dev.nocs.indi.IndiServerSupervisor;
import dev.nocs.target.SimbadResolver;
import dev.nocs.target.Target;
import dev.nocs.target.catalog.CatalogLoader;
import dev.nocs.target.catalog.InMemoryTargetIndex;
import dev.nocs.target.catalog.SolarSystemCatalog;
import java.io.IOException;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class AppBeansConfig {

    @Bean
    java.nio.file.Path nocsDataDir(NocsProperties props) {
        String dir = props.dataDir() != null && !props.dataDir().isBlank()
                ? props.dataDir()
                : DataDirBootstrap.resolveDataDir().toString();
        return java.nio.file.Path.of(dir);
    }

    @Bean
    PlateSolvingService plateSolvingService(
            NocsProperties props,
            AstapInstallationLocator locator,
            AstapInvoker invoker,
            java.nio.file.Path nocsDataDir) {
        String solver = props.platesolving() == null ? "astap" : props.platesolving().solver();
        if ("disabled".equalsIgnoreCase(solver)) {
            return new DisabledPlateSolvingService();
        }
        return new AstapPlateSolver(locator, invoker, props, nocsDataDir);
    }

    @Bean
    AstapInstallService astapInstallService(
            NocsProperties props,
            java.nio.file.Path nocsDataDir,
            EventBus bus,
            AstapInstaller installer) {
        return new AstapInstallService(props, nocsDataDir, bus, installer, AstapInstallSpecs::forCurrent);
    }

    @Bean
    IndiClient indiClient() {
        return new IndiClient();
    }

    @Bean
    CameraImageSink cameraImageSink(ImageStoreService imageStore) {
        return imageStore::accept;
    }

    @Bean
    DeviceService deviceService(IndiClient client, EventBus bus, CameraImageSink sink) {
        return new DeviceService(client, bus, sink);
    }

    @Bean
    IndiServerSupervisor indiServerSupervisor(NocsProperties props, EventBus bus) {
        IndiConfig cfg =
                props.indi() != null
                        ? props.indi()
                        : new IndiConfig(IndiConfig.Mode.DISABLED, "127.0.0.1", 7624, List.of(), null);
        return new IndiServerSupervisor(cfg, bus);
    }

    @Bean
    InMemoryTargetIndex bundledTargetIndex() throws IOException {
        List<Target> all = new ArrayList<>();
        all.addAll(CatalogLoader.loadFromClasspath(
                Thread.currentThread().getContextClassLoader(),
                List.of(
                        "catalogs/messier.tsv",
                        "catalogs/caldwell.tsv",
                        "catalogs/named-stars.tsv",
                        "catalogs/opennngc.tsv")));
        all.addAll(SolarSystemCatalog.staticTargets());
        return new InMemoryTargetIndex(all);
    }

    @Bean
    SimbadResolver simbadResolver(NocsProperties props) {
        return new SimbadResolver(
                props.targets() != null && Boolean.TRUE.equals(props.targets().onlineResolver()),
                props.targets() == null ? null : props.targets().simbadBaseUrl());
    }

    @Bean
    SafetyState safetyState() {
        return new SafetyState();
    }

    @Bean
    SafetyRuleEngine safetyRuleEngine() {
        return new SafetyRuleEngine();
    }

    @Bean
    SafetyRuleParser safetyRuleParser() {
        return new SafetyRuleParser();
    }

    @Bean
    SessionLogSink sessionLogSink(SessionService sessions) {
        return sessions::logEvent;
    }

    @Bean
    SafetyActionDispatcher safetyActionDispatcher(
            DeviceService deviceService, EventBus bus, SessionLogSink sessionLog) {
        return new SafetyActionDispatcher(deviceService.registry(), bus, sessionLog);
    }

    @Bean
    SafetyService safetyService(
            EventBus bus,
            SafetyActionDispatcher dispatcher,
            SafetyRuleEngine engine,
            SafetyState state,
            SafetyRuleParser parser,
            ObservatoryService observatoryService,
            NocsProperties props) {
        Path rulesPath = resolveSafetyPath(props);
        long altitudeMs = props.safety() == null ? 10_000L : props.safety().altitudeEvalIntervalMs();
        long offlineSec = props.safety() == null ? 60L : props.safety().sensorOfflineDefaultSeconds();
        return new SafetyService(
                bus, dispatcher, engine, state, parser, observatoryService, rulesPath, altitudeMs, offlineSec);
    }

    private static Path resolveSafetyPath(NocsProperties props) {
        String configured = props.safety() == null ? null : props.safety().rulesPath();
        if (configured != null && !configured.isBlank()) {
            return Paths.get(configured);
        }
        String dataDir = props.dataDir();
        if (dataDir == null || dataDir.isBlank()) {
            dataDir = System.getProperty("java.io.tmpdir");
        }
        return Paths.get(dataDir).resolve("safety.yaml");
    }
}
