package dev.nocs.config;

import dev.nocs.indi.IndiClient;
import dev.nocs.indi.IndiConfig;
import dev.nocs.indi.IndiServerSupervisor;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import java.io.IOException;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

@Component
@ConditionalOnProperty(name = "nocs.indi.auto-connect", havingValue = "true")
public class IndiConnectionLifecycle {

    private final NocsProperties props;
    private final IndiServerSupervisor supervisor;
    private final IndiClient client;
    private final long startupWaitMs;

    public IndiConnectionLifecycle(
            NocsProperties props,
            IndiServerSupervisor supervisor,
            IndiClient client,
            @Value("${nocs.indi.startup-wait-ms:1000}") long startupWaitMs) {
        this.props = props;
        this.supervisor = supervisor;
        this.client = client;
        this.startupWaitMs = startupWaitMs;
    }

    @PostConstruct
    public void start() throws IOException, InterruptedException {
        if (props.indi() == null || props.indi().mode() == IndiConfig.Mode.DISABLED) {
            return;
        }
        if (props.indi().mode() == IndiConfig.Mode.MANAGED) {
            supervisor.start();
            Thread.sleep(startupWaitMs);
        }
        connectWithRetry(props.indi().host(), props.indi().port());
    }

    private void connectWithRetry(String host, int port) throws IOException, InterruptedException {
        IOException last = null;
        for (int attempt = 1; attempt <= 20; attempt++) {
            try {
                client.connect(host, port);
                return;
            } catch (IOException e) {
                last = e;
                Thread.sleep(250);
            }
        }
        throw last != null ? last : new IOException("INDI connect failed");
    }

    @PreDestroy
    public void stop() {
        try {
            client.close();
        } catch (Exception ignored) {
        }
        supervisor.stop();
    }
}
