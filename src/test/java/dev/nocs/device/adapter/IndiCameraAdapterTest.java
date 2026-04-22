package dev.nocs.device.adapter;

import dev.nocs.device.CameraImageSink;
import dev.nocs.device.CameraState;
import dev.nocs.device.DeviceId;
import dev.nocs.events.EventBus;
import dev.nocs.indi.IndiClient;
import dev.nocs.indi.IndiProperty;
import java.time.Instant;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;

class IndiCameraAdapterTest {

    private final IndiClient client = mock(IndiClient.class);
    private final EventBus bus = new EventBus();
    private final CopyOnWriteArrayList<byte[]> sunk = new CopyOnWriteArrayList<>();
    private final CameraImageSink sink = (camera, bytes, ext) -> sunk.add(bytes);
    private final DeviceId id = new DeviceId("ccd-simulator");

    private IndiCameraAdapter camera() {
        return new IndiCameraAdapter("CCD Simulator", id, client, bus, sink);
    }

    @Test
    void connectForcesUploadClientAndConnectsBlob() throws Exception {
        IndiCameraAdapter c = camera();
        c.connect();

        verify(client).setSwitch(
                eq("CCD Simulator"), eq("CONNECTION"), eq(Map.of("CONNECT", true, "DISCONNECT", false)));
        verify(client).setSwitch(
                eq("CCD Simulator"),
                eq("UPLOAD_MODE"),
                eq(Map.of("UPLOAD_CLIENT", true, "UPLOAD_LOCAL", false, "UPLOAD_BOTH", false)));
        verify(client).enableBlob(eq("CCD Simulator"), eq("Also"));
    }

    @Test
    void coolSetsCoolerAndTemperature() throws Exception {
        IndiCameraAdapter c = camera();
        c.cool(-10.0);

        verify(client).setSwitch(
                eq("CCD Simulator"), eq("CCD_COOLER"), eq(Map.of("COOLER_ON", true, "COOLER_OFF", false)));
        verify(client).setNumber(
                eq("CCD Simulator"), eq("CCD_TEMPERATURE"), eq(Map.of("CCD_TEMPERATURE_VALUE", -10.0)));
    }

    @Test
    void exposeSetsExposureNumber() throws Exception {
        IndiCameraAdapter c = camera();
        c.expose(2.5);

        verify(client).setNumber(
                eq("CCD Simulator"), eq("CCD_EXPOSURE"), eq(Map.of("CCD_EXPOSURE_VALUE", 2.5)));
    }

    @Test
    void stateTransitionsOnProperties() {
        IndiCameraAdapter c = camera();
        assertThat(c.state()).isEqualTo(CameraState.DISCONNECTED);

        c.onProperty(connection(true));
        assertThat(c.state()).isEqualTo(CameraState.IDLE);

        c.onProperty(exposureVector(IndiProperty.State.BUSY, 1.0));
        assertThat(c.state()).isEqualTo(CameraState.EXPOSING);

        c.onBlob(new byte[] {7, 8, 9}, ".fits");
        assertThat(sunk).hasSize(1);
        assertThat(c.state()).isEqualTo(CameraState.IDLE);
    }

    private IndiProperty connection(boolean connected) {
        return new IndiProperty.SwitchVector(
                "CCD Simulator",
                "CONNECTION",
                IndiProperty.State.OK,
                Instant.now(),
                IndiProperty.SwitchRule.ONE_OF_MANY,
                Map.of("CONNECT", connected, "DISCONNECT", !connected));
    }

    private IndiProperty exposureVector(IndiProperty.State state, double value) {
        return new IndiProperty.NumberVector(
                "CCD Simulator", "CCD_EXPOSURE", state, Instant.now(), Map.of("CCD_EXPOSURE_VALUE", value));
    }
}
