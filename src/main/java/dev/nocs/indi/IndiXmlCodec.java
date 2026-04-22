package dev.nocs.indi;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.OutputStreamWriter;
import java.io.Writer;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.function.Consumer;
import javax.xml.stream.XMLInputFactory;
import javax.xml.stream.XMLStreamConstants;
import javax.xml.stream.XMLStreamException;
import javax.xml.stream.XMLStreamReader;

/**
 * Minimal INDI XML codec. INDI uses concatenated XML fragments (no single root),
 * so {@link #readAll} wraps input in a synthetic root to keep the StAX reader happy.
 */
public final class IndiXmlCodec {

    private static final XMLInputFactory INPUT_FACTORY = XMLInputFactory.newInstance();

    static {
        INPUT_FACTORY.setProperty(XMLInputFactory.IS_NAMESPACE_AWARE, Boolean.FALSE);
        INPUT_FACTORY.setProperty(XMLInputFactory.SUPPORT_DTD, Boolean.FALSE);
        INPUT_FACTORY.setProperty("javax.xml.stream.isSupportingExternalEntities", Boolean.FALSE);
    }

    public List<IndiProperty> readAll(String concatenatedXml) throws IOException {
        List<IndiProperty> out = new ArrayList<>();
        readStream(
                new ByteArrayInputStream(
                        ("<root>" + concatenatedXml + "</root>").getBytes(StandardCharsets.UTF_8)),
                out::add);
        return out;
    }

    /** Reads fragments from a stream that is already wrapped as {@code <root>...</root>}. */
    public void readStream(InputStream wrappedInput, Consumer<IndiProperty> sink) throws IOException {
        try {
            XMLStreamReader r = INPUT_FACTORY.createXMLStreamReader(wrappedInput, "UTF-8");
            while (r.hasNext()) {
                int event = r.next();
                if (event != XMLStreamConstants.START_ELEMENT) {
                    continue;
                }
                if ("root".equals(r.getLocalName())) {
                    continue;
                }
                IndiProperty p = readFragment(r);
                if (p != null) {
                    sink.accept(p);
                }
            }
        } catch (XMLStreamException e) {
            throw new IOException("INDI XML parse error", e);
        }
    }

    private IndiProperty readFragment(XMLStreamReader r) throws XMLStreamException {
        String element = r.getLocalName();
        String device = r.getAttributeValue(null, "device");
        String name = r.getAttributeValue(null, "name");
        String stateAttr = r.getAttributeValue(null, "state");
        IndiProperty.State state = IndiProperty.State.parse(stateAttr);
        Instant ts = parseTs(r.getAttributeValue(null, "timestamp"));

        switch (element) {
            case "defSwitchVector", "setSwitchVector", "newSwitchVector" -> {
                IndiProperty.SwitchRule rule = IndiProperty.SwitchRule.parse(r.getAttributeValue(null, "rule"));
                Map<String, Boolean> elements = new LinkedHashMap<>();
                while (r.hasNext()) {
                    int ev = r.next();
                    if (ev == XMLStreamConstants.START_ELEMENT
                            && (r.getLocalName().equals("defSwitch") || r.getLocalName().equals("oneSwitch"))) {
                        String en = r.getAttributeValue(null, "name");
                        String text = r.getElementText().trim();
                        elements.put(en, "On".equalsIgnoreCase(text));
                    } else if (ev == XMLStreamConstants.END_ELEMENT && r.getLocalName().equals(element)) {
                        break;
                    }
                }
                return new IndiProperty.SwitchVector(device, name, state, ts, rule, elements);
            }
            case "defNumberVector", "setNumberVector", "newNumberVector" -> {
                Map<String, Double> elements = new LinkedHashMap<>();
                while (r.hasNext()) {
                    int ev = r.next();
                    if (ev == XMLStreamConstants.START_ELEMENT
                            && (r.getLocalName().equals("defNumber") || r.getLocalName().equals("oneNumber"))) {
                        String en = r.getAttributeValue(null, "name");
                        String text = r.getElementText().trim();
                        elements.put(en, parseDouble(text));
                    } else if (ev == XMLStreamConstants.END_ELEMENT && r.getLocalName().equals(element)) {
                        break;
                    }
                }
                return new IndiProperty.NumberVector(device, name, state, ts, elements);
            }
            case "defTextVector", "setTextVector", "newTextVector" -> {
                Map<String, String> elements = new LinkedHashMap<>();
                while (r.hasNext()) {
                    int ev = r.next();
                    if (ev == XMLStreamConstants.START_ELEMENT
                            && (r.getLocalName().equals("defText") || r.getLocalName().equals("oneText"))) {
                        String en = r.getAttributeValue(null, "name");
                        String text = r.getElementText();
                        elements.put(en, text == null ? "" : text);
                    } else if (ev == XMLStreamConstants.END_ELEMENT && r.getLocalName().equals(element)) {
                        break;
                    }
                }
                return new IndiProperty.TextVector(device, name, state, ts, elements);
            }
            case "defBLOBVector" -> {
                skipToClose(r, element);
                return new IndiProperty.BlobVector(device, name, state, ts, null, null);
            }
            case "setBLOBVector" -> {
                String format = null;
                byte[] bytes = null;
                while (r.hasNext()) {
                    int ev = r.next();
                    if (ev == XMLStreamConstants.START_ELEMENT && r.getLocalName().equals("oneBLOB")) {
                        format = r.getAttributeValue(null, "format");
                        String base64 = r.getElementText();
                        bytes = Base64.getMimeDecoder().decode(base64.replaceAll("\\s", ""));
                    } else if (ev == XMLStreamConstants.END_ELEMENT && r.getLocalName().equals(element)) {
                        break;
                    }
                }
                return new IndiProperty.BlobVector(device, name, state, ts, format, bytes);
            }
            default -> {
                skipToClose(r, element);
                return null;
            }
        }
    }

    private void skipToClose(XMLStreamReader r, String name) throws XMLStreamException {
        int depth = 1;
        while (r.hasNext() && depth > 0) {
            int ev = r.next();
            if (ev == XMLStreamConstants.START_ELEMENT) {
                depth++;
            } else if (ev == XMLStreamConstants.END_ELEMENT) {
                depth--;
            }
        }
    }

    private static double parseDouble(String text) {
        if (text == null || text.isBlank()) {
            return 0.0;
        }
        try {
            return Double.parseDouble(text);
        } catch (NumberFormatException e) {
            return 0.0;
        }
    }

    private static Instant parseTs(String ts) {
        if (ts == null || ts.isBlank()) {
            return Instant.now();
        }
        try {
            return Instant.parse(ts.endsWith("Z") ? ts : ts + "Z");
        } catch (Exception e) {
            return Instant.now();
        }
    }

    public void writeGetProperties(OutputStream out, String device, String property) throws IOException {
        Writer w = writer(out);
        w.write("<getProperties version=\"1.7\"");
        if (device != null) {
            w.write(" device=\"" + escape(device) + "\"");
        }
        if (property != null) {
            w.write(" name=\"" + escape(property) + "\"");
        }
        w.write("/>\n");
        w.flush();
    }

    public void writeEnableBlob(OutputStream out, String device, String mode) throws IOException {
        Writer w = writer(out);
        w.write("<enableBLOB device=\"" + escape(device) + "\">" + mode + "</enableBLOB>\n");
        w.flush();
    }

    public void writeNewSwitchVector(OutputStream out, String device, String name, Map<String, Boolean> elements)
            throws IOException {
        Writer w = writer(out);
        w.write("<newSwitchVector device=\"" + escape(device) + "\" name=\"" + escape(name) + "\">\n");
        for (var e : elements.entrySet()) {
            w.write("  <oneSwitch name=\"" + escape(e.getKey()) + "\">" + (e.getValue() ? "On" : "Off")
                    + "</oneSwitch>\n");
        }
        w.write("</newSwitchVector>\n");
        w.flush();
    }

    public void writeNewNumberVector(OutputStream out, String device, String name, Map<String, Double> elements)
            throws IOException {
        Writer w = writer(out);
        w.write("<newNumberVector device=\"" + escape(device) + "\" name=\"" + escape(name) + "\">\n");
        for (var e : elements.entrySet()) {
            w.write("  <oneNumber name=\"" + escape(e.getKey()) + "\">"
                    + String.format(Locale.ROOT, "%s", e.getValue()) + "</oneNumber>\n");
        }
        w.write("</newNumberVector>\n");
        w.flush();
    }

    public void writeNewTextVector(OutputStream out, String device, String name, Map<String, String> elements)
            throws IOException {
        Writer w = writer(out);
        w.write("<newTextVector device=\"" + escape(device) + "\" name=\"" + escape(name) + "\">\n");
        for (var e : elements.entrySet()) {
            w.write("  <oneText name=\"" + escape(e.getKey()) + "\">" + escape(e.getValue()) + "</oneText>\n");
        }
        w.write("</newTextVector>\n");
        w.flush();
    }

    private Writer writer(OutputStream out) {
        return new OutputStreamWriter(out, StandardCharsets.UTF_8);
    }

    private static String escape(String s) {
        if (s == null) {
            return "";
        }
        return s.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\"", "&quot;");
    }
}
