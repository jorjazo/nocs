package dev.nocs.indi;

import java.io.IOException;
import java.io.InputStream;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.util.Collection;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicBoolean;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Sinks;

public class IndiClient implements AutoCloseable {

    private static final Logger log = LoggerFactory.getLogger(IndiClient.class);

    @FunctionalInterface
    public interface BlobCallback {
        void accept(String device, String propertyName, String format, byte[] bytes);
    }

    private final IndiXmlCodec codec = new IndiXmlCodec();
    private final IndiFragmentSplitter splitter = new IndiFragmentSplitter();
    private final Map<String, Map<String, IndiProperty>> registry = new ConcurrentHashMap<>();
    private final Sinks.Many<PropertyUpdate> sink =
            Sinks.many().multicast().onBackpressureBuffer(2048, false);
    private final AtomicBoolean running = new AtomicBoolean(false);

    private volatile BlobCallback blobCallback = (d, n, f, b) -> {};

    private volatile Socket socket;
    private volatile Thread reader;

    public void onBlob(BlobCallback cb) {
        this.blobCallback = cb == null ? (d, n, f, b) -> {} : cb;
    }

    public void connect(String host, int port) throws IOException {
        close();
        registry.clear();
        splitter.clear();
        Socket s = new Socket();
        s.connect(new InetSocketAddress(host, port), 5000);
        s.setTcpNoDelay(true);
        this.socket = s;
        running.set(true);
        this.reader = Thread.ofVirtual().name("indi-reader").start(this::readLoop);
        codec.writeGetProperties(s.getOutputStream(), null, null);
    }

    private void readLoop() {
        try (InputStream in = socket.getInputStream()) {
            byte[] buf = new byte[8192];
            int n;
            while (running.get() && (n = in.read(buf)) != -1) {
                splitter.append(buf, 0, n);
                String frag;
                while ((frag = splitter.pollFragment()) != null) {
                    List<IndiProperty> props = codec.readAll(frag);
                    for (IndiProperty p : props) {
                        onProperty(p);
                    }
                }
            }
        } catch (IOException e) {
            if (running.get()) {
                log.warn("INDI read loop ended: {}", e.toString());
            }
        } finally {
            running.set(false);
        }
    }

    private void onProperty(IndiProperty p) {
        if (p instanceof IndiProperty.BlobVector blob && blob.bytes() != null) {
            registry.computeIfAbsent(p.device(), k -> new ConcurrentHashMap<>()).put(p.name(), p);
            try {
                blobCallback.accept(blob.device(), blob.name(), blob.format(), blob.bytes());
            } catch (RuntimeException e) {
                log.warn("BLOB callback failed for {}/{}", blob.device(), blob.name(), e);
            }
            sink.tryEmitNext(new PropertyUpdate(PropertyUpdate.Kind.SET, p));
            return;
        }
        PropertyUpdate.Kind kind =
                registry.computeIfAbsent(p.device(), k -> new ConcurrentHashMap<>()).put(p.name(), p) == null
                        ? PropertyUpdate.Kind.DEFINED
                        : PropertyUpdate.Kind.SET;
        sink.tryEmitNext(new PropertyUpdate(kind, p));
    }

    public Flux<PropertyUpdate> updates() {
        return sink.asFlux();
    }

    public Collection<IndiProperty> properties(String device) {
        Map<String, IndiProperty> m = registry.get(device);
        return m == null ? List.of() : m.values();
    }

    public IndiProperty property(String device, String name) {
        Map<String, IndiProperty> m = registry.get(device);
        return m == null ? null : m.get(name);
    }

    public Set<String> devices() {
        return registry.keySet();
    }

    public synchronized void setSwitch(String device, String name, Map<String, Boolean> elements)
            throws IOException {
        var out = socket.getOutputStream();
        codec.writeNewSwitchVector(out, device, name, elements);
        out.flush();
    }

    public synchronized void setNumber(String device, String name, Map<String, Double> elements)
            throws IOException {
        var out = socket.getOutputStream();
        codec.writeNewNumberVector(out, device, name, elements);
        out.flush();
    }

    public synchronized void setText(String device, String name, Map<String, String> elements)
            throws IOException {
        var out = socket.getOutputStream();
        codec.writeNewTextVector(out, device, name, elements);
        out.flush();
    }

    public synchronized void enableBlob(String device, String mode) throws IOException {
        var out = socket.getOutputStream();
        codec.writeEnableBlob(out, device, mode);
        out.flush();
    }

    public boolean isConnected() {
        return running.get() && socket != null && !socket.isClosed();
    }

    @Override
    public synchronized void close() {
        running.set(false);
        if (socket != null) {
            try {
                socket.close();
            } catch (IOException ignored) {
            }
            socket = null;
        }
        if (reader != null) {
            try {
                reader.join(2000);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
            reader = null;
        }
    }
}
