package dev.nocs.indi;

import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import org.awaitility.Awaitility;
import org.junit.jupiter.api.Test;
import reactor.core.Disposable;

import static org.assertj.core.api.Assertions.assertThat;

class IndiClientTest {

    @Test
    void connectsAndSendsGetProperties() throws Exception {
        try (FakeIndiServer server = new FakeIndiServer();
                IndiClient client = new IndiClient()) {

            client.connect("127.0.0.1", server.port());
            server.awaitConnected();

            Awaitility.await().atMost(Duration.ofSeconds(2))
                    .untilAsserted(() -> assertThat(server.receivedText()).contains("<getProperties"));
        }
    }

    @Test
    void receivesDefinesAndBuildsRegistry() throws Exception {
        try (FakeIndiServer server = new FakeIndiServer();
                IndiClient client = new IndiClient()) {

            client.connect("127.0.0.1", server.port());
            server.awaitConnected();

            server.send(
                    """
                    <defSwitchVector device="Telescope Simulator" name="CONNECTION" state="Idle" rule="OneOfMany">
                        <defSwitch name="CONNECT">Off</defSwitch>
                        <defSwitch name="DISCONNECT">On</defSwitch>
                    </defSwitchVector>
                    """);

            Awaitility.await().atMost(Duration.ofSeconds(2))
                    .untilAsserted(() -> assertThat(client.properties("Telescope Simulator"))
                            .anyMatch(p -> p.name().equals("CONNECTION")));
        }
    }

    @Test
    void publishesUpdatesToSubscribers() throws Exception {
        try (FakeIndiServer server = new FakeIndiServer();
                IndiClient client = new IndiClient()) {

            List<PropertyUpdate> seen = new CopyOnWriteArrayList<>();
            Disposable sub = client.updates().subscribe(seen::add);

            client.connect("127.0.0.1", server.port());
            server.awaitConnected();

            server.send(
                    """
                    <defNumberVector device="CCD Simulator" name="CCD_EXPOSURE" state="Idle">
                        <defNumber name="CCD_EXPOSURE_VALUE">0</defNumber>
                    </defNumberVector>
                    """);
            server.send(
                    """
                    <setNumberVector device="CCD Simulator" name="CCD_EXPOSURE" state="Busy">
                        <oneNumber name="CCD_EXPOSURE_VALUE">5</oneNumber>
                    </setNumberVector>
                    """);

            Awaitility.await().atMost(Duration.ofSeconds(2)).untilAsserted(() -> {
                assertThat(seen).hasSizeGreaterThanOrEqualTo(2);
                assertThat(seen.getFirst().kind()).isEqualTo(PropertyUpdate.Kind.DEFINED);
                assertThat(seen.get(1).kind()).isEqualTo(PropertyUpdate.Kind.SET);
            });
            sub.dispose();
        }
    }

    @Test
    void listsDiscoveredDevices() throws Exception {
        try (FakeIndiServer server = new FakeIndiServer();
                IndiClient client = new IndiClient()) {
            client.connect("127.0.0.1", server.port());
            server.awaitConnected();

            server.send(
                    "<defSwitchVector device=\"Telescope Simulator\" name=\"CONNECTION\" state=\"Idle\"><defSwitch name=\"CONNECT\">Off</defSwitch><defSwitch name=\"DISCONNECT\">On</defSwitch></defSwitchVector>\n");
            server.send(
                    "<defNumberVector device=\"CCD Simulator\" name=\"CCD_EXPOSURE\" state=\"Idle\"><defNumber name=\"CCD_EXPOSURE_VALUE\">0</defNumber></defNumberVector>\n");

            Awaitility.await().atMost(Duration.ofSeconds(2))
                    .untilAsserted(() -> assertThat(new ArrayList<>(client.devices()))
                            .contains("Telescope Simulator", "CCD Simulator"));
        }
    }

    @Test
    void receivesBlob() throws Exception {
        try (FakeIndiServer server = new FakeIndiServer();
                IndiClient client = new IndiClient()) {

            List<byte[]> blobs = new CopyOnWriteArrayList<>();
            client.onBlob((device, propertyName, format, bytes) -> blobs.add(bytes));

            client.connect("127.0.0.1", server.port());
            server.awaitConnected();

            client.enableBlob("CCD Simulator", "Also");

            server.send("<setBLOBVector device=\"CCD Simulator\" name=\"CCD1\" state=\"Ok\">"
                    + "<oneBLOB name=\"CCD1\" size=\"3\" format=\".fits\">AQID</oneBLOB>"
                    + "</setBLOBVector>\n");

            Awaitility.await().atMost(Duration.ofSeconds(2))
                    .untilAsserted(() -> assertThat(blobs).hasSize(1));
            assertThat(blobs.getFirst()).containsExactly(1, 2, 3);
        }
    }
}
