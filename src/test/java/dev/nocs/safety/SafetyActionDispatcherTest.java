package dev.nocs.safety;

import dev.nocs.device.Camera;
import dev.nocs.device.CameraState;
import dev.nocs.device.Device;
import dev.nocs.device.DeviceId;
import dev.nocs.device.DeviceKind;
import dev.nocs.device.DeviceRegistry;
import dev.nocs.device.Mount;
import dev.nocs.device.MountState;
import dev.nocs.events.Event;
import dev.nocs.events.EventBus;
import dev.nocs.events.Topic;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class SafetyActionDispatcherTest {

    private final EventBus bus = new EventBus();
    private final DeviceRegistry registry = new DeviceRegistry();
    private final RecordingMount mount = new RecordingMount();
    private final RecordingCamera camera = new RecordingCamera();
    private final RecordingSessionLog sessionLog = new RecordingSessionLog();
    private final SafetyActionDispatcher dispatcher = new SafetyActionDispatcher(registry, bus, sessionLog);

    SafetyActionDispatcherTest() {
        registry.add(mount);
        registry.add(camera);
        mount.connect();
        camera.connect();
    }

    @Test
    void pauseSequenceOnlyEmitsBusEvent() {
        CopyOnWriteArrayList<Event> seen = subscribeAll();
        SafetyRule r = new SafetyRule("paus", new SafetyCondition.HumidityAbove(90), SafetyAction.PAUSE_SEQUENCE);

        dispatcher.dispatch(new TriggeredRule(r, r.condition(), Instant.now()), "rule-trigger");

        assertThat(mount.parked).isZero();
        assertThat(camera.aborted).isZero();
        assertThat(seen.stream()
                        .filter(e -> e.topic() == Topic.SEQUENCE && e.type().equals("pause_requested"))
                        .count())
                .isEqualTo(1);
        assertThat(seen.stream()
                        .filter(e -> e.topic() == Topic.SAFETY && e.type().equals("rule_triggered"))
                        .count())
                .isEqualTo(1);
    }

    @Test
    void abortAndParkParksMountsAndEmitsAbort() {
        CopyOnWriteArrayList<Event> seen = subscribeAll();
        SafetyRule r = new SafetyRule("low", new SafetyCondition.AltitudeBelow(20), SafetyAction.ABORT_AND_PARK);

        dispatcher.dispatch(new TriggeredRule(r, r.condition(), Instant.now()), "rule-trigger");

        assertThat(mount.parked).isEqualTo(1);
        assertThat(mount.eStopped).isZero();
        assertThat(camera.aborted).isZero();
        assertThat(seen.stream()
                        .filter(e -> e.topic() == Topic.SEQUENCE && e.type().equals("abort_requested"))
                        .count())
                .isEqualTo(1);
    }

    @Test
    void eStopAbortsExposuresParksMountsAndTransitionsBoth() {
        CopyOnWriteArrayList<Event> seen = subscribeAll();

        dispatcher.eStop("manual button", "client-1");

        assertThat(camera.aborted).isEqualTo(1);
        assertThat(camera.eStopped).isEqualTo(1);
        assertThat(mount.parked).isEqualTo(1);
        assertThat(mount.eStopped).isEqualTo(1);

        assertThat(seen.stream()
                        .filter(e -> e.topic() == Topic.SEQUENCE && e.type().equals("abort_requested"))
                        .count())
                .isEqualTo(1);
        assertThat(seen.stream()
                        .filter(e -> e.topic() == Topic.SAFETY && e.type().equals("e_stopped"))
                        .count())
                .isEqualTo(1);
        assertThat(sessionLog.events).anyMatch(e -> e.type.equals("e_stop"));
    }

    @Test
    void resetClearsEStopOnAllDevices() {
        dispatcher.eStop("test", "client-1");
        assertThat(mount.state()).isEqualTo(MountState.E_STOPPED);
        assertThat(camera.state()).isEqualTo(CameraState.E_STOPPED);

        dispatcher.reset("client-1");

        assertThat(mount.state()).isEqualTo(MountState.IDLE);
        assertThat(camera.state()).isEqualTo(CameraState.IDLE);
    }

    private CopyOnWriteArrayList<Event> subscribeAll() {
        CopyOnWriteArrayList<Event> seen = new CopyOnWriteArrayList<>();
        bus.subscribeAll().subscribe(seen::add);
        return seen;
    }

    private static final class RecordingMount implements Mount {
        int parked;
        int eStopped;
        private MountState state = MountState.DISCONNECTED;

        @Override
        public DeviceId id() {
            return new DeviceId("mount-rec");
        }

        @Override
        public String indiName() {
            return "RecMount";
        }

        @Override
        public DeviceKind kind() {
            return DeviceKind.MOUNT;
        }

        @Override
        public boolean isConnected() {
            return state != MountState.DISCONNECTED;
        }

        @Override
        public void connect() {
            state = MountState.IDLE;
        }

        @Override
        public void disconnect() {
            state = MountState.DISCONNECTED;
        }

        @Override
        public MountState state() {
            return state;
        }

        @Override
        public void slew(double r, double d) {}

        @Override
        public void syncTo(double r, double d) {}

        @Override
        public void park() {
            parked++;
        }

        @Override
        public void unpark() {}

        @Override
        public void abort() {}

        @Override
        public void emergencyStop() {
            eStopped++;
            state = MountState.E_STOPPED;
        }

        @Override
        public void resetEStop() {
            if (state == MountState.E_STOPPED) {
                state = MountState.IDLE;
            }
        }
    }

    private static final class RecordingCamera implements Camera {
        int aborted;
        int eStopped;
        private CameraState state = CameraState.DISCONNECTED;

        @Override
        public DeviceId id() {
            return new DeviceId("camera-rec");
        }

        @Override
        public String indiName() {
            return "RecCcd";
        }

        @Override
        public DeviceKind kind() {
            return DeviceKind.CAMERA;
        }

        @Override
        public boolean isConnected() {
            return state != CameraState.DISCONNECTED;
        }

        @Override
        public void connect() {
            state = CameraState.IDLE;
        }

        @Override
        public void disconnect() {
            state = CameraState.DISCONNECTED;
        }

        @Override
        public CameraState state() {
            return state;
        }

        @Override
        public void cool(double s) {}

        @Override
        public void expose(double s) {}

        @Override
        public void abortExposure() {
            aborted++;
        }

        @Override
        public Double currentTemperatureCelsius() {
            return null;
        }

        @Override
        public void emergencyStop() {
            eStopped++;
            state = CameraState.E_STOPPED;
        }

        @Override
        public void resetEStop() {
            if (state == CameraState.E_STOPPED) {
                state = CameraState.IDLE;
            }
        }
    }

    static final class LoggedEvent {
        final String topic;
        final String type;
        final Map<String, Object> payload;

        LoggedEvent(String topic, String type, Map<String, Object> payload) {
            this.topic = topic;
            this.type = type;
            this.payload = payload;
        }
    }

    static final class RecordingSessionLog implements SessionLogSink {
        final List<LoggedEvent> events = new java.util.ArrayList<>();

        @Override
        public void log(String topic, String type, Map<String, Object> payload) {
            events.add(new LoggedEvent(topic, type, payload));
        }
    }
}
