package dev.nocs.config;

import dev.nocs.device.CameraImageSink;
import dev.nocs.device.DeviceService;
import dev.nocs.events.EventBus;
import dev.nocs.image.ImageStoreService;
import dev.nocs.indi.IndiClient;
import dev.nocs.indi.IndiConfig;
import dev.nocs.indi.IndiServerSupervisor;
import dev.nocs.target.SimbadResolver;
import dev.nocs.target.Target;
import dev.nocs.target.catalog.CatalogLoader;
import dev.nocs.target.catalog.InMemoryTargetIndex;
import dev.nocs.target.catalog.SolarSystemCatalog;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class AppBeansConfig {

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
}
