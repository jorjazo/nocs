package dev.nocs.events;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import dev.nocs.domain.events.EquipmentConnected;
import dev.nocs.domain.events.EquipmentDisconnected;
import dev.nocs.domain.events.EquipmentStatusChanged;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArraySet;

/**
 * Broadcasts equipment events to all connected SSE clients.
 */
@Component
public class EquipmentSseBroadcaster {

    private static final Logger log = LoggerFactory.getLogger(EquipmentSseBroadcaster.class);
    private static final long SSE_TIMEOUT_MS = 0; // no timeout - long-lived connection

    private final ObjectMapper objectMapper;
    private final CopyOnWriteArraySet<SseEmitter> emitters = new CopyOnWriteArraySet<>();

    public EquipmentSseBroadcaster(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    public SseEmitter addEmitter() {
        SseEmitter emitter = new SseEmitter(SSE_TIMEOUT_MS);
        emitters.add(emitter);
        emitter.onCompletion(() -> emitters.remove(emitter));
        emitter.onTimeout(() -> emitters.remove(emitter));
        emitter.onError(e -> {
            log.warn("SSE emitter error, removing: {}", e.getMessage());
            emitters.remove(emitter);
        });
        return emitter;
    }

    public void broadcast(EquipmentStatusChanged event) {
        Map<String, Object> data = new HashMap<>();
        data.put("equipmentType", event.equipmentType().name());
        data.put("status", event.statusPayload());
        if (event.driverStatus() != null) {
            data.put("driverStatus", Map.of(
                    "connectionState", event.driverStatus().connectionState().name(),
                    "lastError", event.driverStatus().lastError() != null ? event.driverStatus().lastError() : ""
            ));
        }
        broadcast("equipment_status", data);
    }

    public void broadcast(EquipmentConnected event) {
        Map<String, Object> data = new HashMap<>();
        data.put("equipmentType", event.equipmentType().name());
        if (event.driverStatus() != null) {
            data.put("driverStatus", Map.of(
                    "connectionState", event.driverStatus().connectionState().name(),
                    "lastError", event.driverStatus().lastError() != null ? event.driverStatus().lastError() : ""
            ));
        }
        broadcast("equipment_connected", data);
    }

    public void broadcast(EquipmentDisconnected event) {
        Map<String, Object> data = new HashMap<>();
        data.put("equipmentType", event.equipmentType().name());
        data.put("reason", event.reason() != null ? event.reason() : "");
        broadcast("equipment_disconnected", data);
    }

    private void broadcast(String eventType, Map<String, Object> data) {
        String json;
        try {
            json = objectMapper.writeValueAsString(data);
        } catch (JsonProcessingException e) {
            log.error("Failed to serialize event: {}", e.getMessage());
            return;
        }
        emitters.removeIf(emitter -> {
            try {
                emitter.send(SseEmitter.event().name(eventType).data(json));
                return false;
            } catch (IOException e) {
                log.debug("Failed to send to emitter: {}", e.getMessage());
                return true;
            }
        });
    }
}
