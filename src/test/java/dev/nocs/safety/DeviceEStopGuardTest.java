package dev.nocs.safety;

import dev.nocs.device.DeviceId;
import dev.nocs.device.adapter.IndiCameraAdapter;
import dev.nocs.device.adapter.IndiMountAdapter;
import dev.nocs.device.CameraState;
import dev.nocs.device.MountState;
import dev.nocs.events.EventBus;
import dev.nocs.indi.IndiClient;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;

class DeviceEStopGuardTest {

    @Test
    void mountRejectsCommandsAfterEmergencyStop() {
        IndiClient client = mock(IndiClient.class);
        EventBus bus = new EventBus();
        IndiMountAdapter mount = new IndiMountAdapter("Sim", new DeviceId("sim"), client, bus);

        mount.emergencyStop();
        assertThat(mount.state()).isEqualTo(MountState.E_STOPPED);

        assertThatThrownBy(() -> mount.slew(0, 0)).isInstanceOf(DeviceEStoppedException.class);
        assertThatThrownBy(() -> mount.park()).isInstanceOf(DeviceEStoppedException.class);
        assertThatThrownBy(() -> mount.unpark()).isInstanceOf(DeviceEStoppedException.class);
        assertThatThrownBy(() -> mount.syncTo(0, 0)).isInstanceOf(DeviceEStoppedException.class);

        mount.resetEStop();
        assertThat(mount.state()).isEqualTo(MountState.IDLE);
    }

    @Test
    void cameraRejectsCommandsAfterEmergencyStop() {
        IndiClient client = mock(IndiClient.class);
        EventBus bus = new EventBus();
        IndiCameraAdapter camera =
                new IndiCameraAdapter("SimCcd", new DeviceId("simccd"), client, bus, (id, b, fmt) -> {});

        camera.emergencyStop();
        assertThat(camera.state()).isEqualTo(CameraState.E_STOPPED);

        assertThatThrownBy(() -> camera.expose(1.0)).isInstanceOf(DeviceEStoppedException.class);
        assertThatThrownBy(() -> camera.cool(-10)).isInstanceOf(DeviceEStoppedException.class);
        assertThatThrownBy(() -> camera.abortExposure()).isInstanceOf(DeviceEStoppedException.class);

        camera.resetEStop();
        assertThat(camera.state()).isEqualTo(CameraState.IDLE);
    }

    @Test
    void resetIsNoopWhenNotEStopped() {
        IndiClient client = mock(IndiClient.class);
        EventBus bus = new EventBus();
        IndiMountAdapter mount = new IndiMountAdapter("Sim", new DeviceId("sim"), client, bus);

        MountState before = mount.state();
        mount.resetEStop();
        assertThat(mount.state()).isEqualTo(before);
    }
}
