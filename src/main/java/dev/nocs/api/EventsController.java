package dev.nocs.api;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.nocs.domain.EquipmentType;
import dev.nocs.events.EquipmentSseBroadcaster;
import dev.nocs.service.CameraService;
import dev.nocs.service.FilterWheelService;
import dev.nocs.service.FocuserService;
import dev.nocs.service.MountService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.util.Map;

@Tag(name = "Events", description = "Server-Sent Events stream for equipment status updates")
@RestController
@RequestMapping("/events")
public class EventsController {

    private final EquipmentSseBroadcaster broadcaster;
    private final MountService mountService;
    private final CameraService cameraService;
    private final FocuserService focuserService;
    private final FilterWheelService filterWheelService;
    private final ObjectMapper objectMapper;

    public EventsController(
            EquipmentSseBroadcaster broadcaster,
            MountService mountService,
            CameraService cameraService,
            FocuserService focuserService,
            FilterWheelService filterWheelService,
            ObjectMapper objectMapper) {
        this.broadcaster = broadcaster;
        this.mountService = mountService;
        this.cameraService = cameraService;
        this.focuserService = focuserService;
        this.filterWheelService = filterWheelService;
        this.objectMapper = objectMapper;
    }

    @Operation(summary = "Subscribe to equipment events", description = "Returns an SSE stream. Sends initial snapshot on connect, then equipment_status, equipment_connected, equipment_disconnected events as they occur.")
    @ApiResponse(responseCode = "200", description = "SSE stream")
    @GetMapping(produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public ResponseEntity<SseEmitter> stream() {
        SseEmitter emitter = broadcaster.addEmitter();
        sendInitialSnapshot(emitter);
        return ResponseEntity.ok(emitter);
    }

    private void sendInitialSnapshot(SseEmitter emitter) {
        try {
            mountService.getStatus().ifPresent(status ->
                    sendEventUnchecked(emitter, "equipment_status", Map.of(
                            "equipmentType", EquipmentType.MOUNT.name(),
                            "status", status
                    )));
            cameraService.getStatus().ifPresent(status ->
                    sendEventUnchecked(emitter, "equipment_status", Map.of(
                            "equipmentType", EquipmentType.CAMERA.name(),
                            "status", status
                    )));
            focuserService.getStatus().ifPresent(status -> {
                var data = new java.util.HashMap<String, Object>();
                data.put("equipmentType", EquipmentType.FOCUSER.name());
                data.put("status", status);
                focuserService.getDriverStatus().ifPresent(ds ->
                        data.put("driverStatus", Map.of(
                                "connectionState", ds.connectionState().name(),
                                "lastError", ds.lastError() != null ? ds.lastError() : ""
                        )));
                sendEventUnchecked(emitter, "equipment_status", data);
            });
            filterWheelService.getStatus().ifPresent(status ->
                    sendEventUnchecked(emitter, "equipment_status", Map.of(
                            "equipmentType", EquipmentType.FILTER_WHEEL.name(),
                            "status", status
                    )));
        } catch (Exception e) {
            emitter.completeWithError(e);
        }
    }

    private void sendEventUnchecked(SseEmitter emitter, String eventType, Map<String, Object> data) {
        try {
            sendEvent(emitter, eventType, data);
        } catch (IOException e) {
            throw new RuntimeException(e);
        }
    }

    private void sendEvent(SseEmitter emitter, String eventType, Map<String, Object> data) throws IOException {
        String json = objectMapper.writeValueAsString(data);
        emitter.send(SseEmitter.event().name(eventType).data(json));
    }
}
