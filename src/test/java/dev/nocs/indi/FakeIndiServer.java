package dev.nocs.indi;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.CountDownLatch;

/** Minimal in-process TCP server used only by {@link IndiClientTest}. */
public final class FakeIndiServer implements AutoCloseable {

    private final ServerSocket server;
    private final CountDownLatch connected = new CountDownLatch(1);
    private volatile Socket clientSocket;
    private final StringBuilder received = new StringBuilder();

    public FakeIndiServer() throws IOException {
        this.server = new ServerSocket(0, 50, InetAddress.getLoopbackAddress());
        Thread.ofVirtual()
                .name("fake-indi-accept")
                .start(() -> {
                    try {
                        Socket sock = server.accept();
                        this.clientSocket = sock;
                        connected.countDown();
                        byte[] buf = new byte[4096];
                        int n;
                        while ((n = sock.getInputStream().read(buf)) != -1) {
                            synchronized (received) {
                                received.append(new String(buf, 0, n, StandardCharsets.UTF_8));
                            }
                        }
                    } catch (IOException ignored) {
                    }
                });
    }

    public int port() {
        return server.getLocalPort();
    }

    public void awaitConnected() throws InterruptedException {
        connected.await();
    }

    public String receivedText() {
        synchronized (received) {
            return received.toString();
        }
    }

    public void send(String xml) throws IOException {
        Socket s = clientSocket;
        if (s == null) {
            throw new IOException("no client connected");
        }
        OutputStream out = s.getOutputStream();
        out.write(xml.getBytes(StandardCharsets.UTF_8));
        out.flush();
    }

    @Override
    public void close() throws IOException {
        try {
            if (clientSocket != null) {
                clientSocket.close();
            }
        } catch (IOException ignored) {
        }
        server.close();
    }
}
