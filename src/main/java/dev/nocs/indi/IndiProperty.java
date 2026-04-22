package dev.nocs.indi;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;

public sealed interface IndiProperty
        permits IndiProperty.SwitchVector,
                IndiProperty.NumberVector,
                IndiProperty.TextVector,
                IndiProperty.BlobVector {

    String device();

    String name();

    State state();

    Instant timestamp();

    enum State {
        IDLE,
        OK,
        BUSY,
        ALERT;

        public static State parse(String s) {
            if (s == null) {
                return IDLE;
            }
            return switch (s) {
                case "Ok" -> OK;
                case "Busy" -> BUSY;
                case "Alert" -> ALERT;
                default -> IDLE;
            };
        }
    }

    enum SwitchRule {
        ONE_OF_MANY,
        AT_MOST_ONE,
        ANY_OF_MANY;

        public static SwitchRule parse(String s) {
            if (s == null) {
                return ONE_OF_MANY;
            }
            return switch (s) {
                case "AtMostOne" -> AT_MOST_ONE;
                case "AnyOfMany" -> ANY_OF_MANY;
                default -> ONE_OF_MANY;
            };
        }
    }

    record SwitchVector(
            String device,
            String name,
            State state,
            Instant timestamp,
            SwitchRule rule,
            Map<String, Boolean> elements)
            implements IndiProperty {

        public SwitchVector {
            elements = elements == null ? Map.of() : Map.copyOf(elements);
        }
    }

    record NumberVector(
            String device,
            String name,
            State state,
            Instant timestamp,
            Map<String, Double> elements)
            implements IndiProperty {

        public NumberVector {
            elements = elements == null ? Map.of() : Map.copyOf(elements);
        }
    }

    record TextVector(
            String device,
            String name,
            State state,
            Instant timestamp,
            Map<String, String> elements)
            implements IndiProperty {

        public TextVector {
            elements = elements == null ? Map.of() : Map.copyOf(elements);
        }
    }

    record BlobVector(String device, String name, State state, Instant timestamp, String format, byte[] bytes)
            implements IndiProperty {}

    static Map<String, String> linked() {
        return new LinkedHashMap<>();
    }
}
