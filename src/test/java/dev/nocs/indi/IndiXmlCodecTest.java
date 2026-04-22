package dev.nocs.indi;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class IndiXmlCodecTest {

    private String fixture(String name) throws Exception {
        try (InputStream in = getClass().getResourceAsStream("/indi/fixtures/" + name)) {
            return new String(in.readAllBytes(), StandardCharsets.UTF_8);
        }
    }

    @Test
    void parsesDefSwitchVector() throws Exception {
        IndiXmlCodec codec = new IndiXmlCodec();
        List<IndiProperty> props = codec.readAll(fixture("defSwitchVector.xml"));
        assertThat(props).hasSize(1);
        IndiProperty.SwitchVector sw = (IndiProperty.SwitchVector) props.getFirst();
        assertThat(sw.device()).isEqualTo("Telescope Simulator");
        assertThat(sw.name()).isEqualTo("CONNECTION");
        assertThat(sw.elements()).containsEntry("CONNECT", false).containsEntry("DISCONNECT", true);
        assertThat(sw.rule()).isEqualTo(IndiProperty.SwitchRule.ONE_OF_MANY);
    }

    @Test
    void parsesDefNumberVector() throws Exception {
        IndiXmlCodec codec = new IndiXmlCodec();
        List<IndiProperty> props = codec.readAll(fixture("defNumberVector.xml"));
        IndiProperty.NumberVector n = (IndiProperty.NumberVector) props.getFirst();
        assertThat(n.device()).isEqualTo("CCD Simulator");
        assertThat(n.name()).isEqualTo("CCD_EXPOSURE");
        assertThat(n.elements()).containsEntry("CCD_EXPOSURE_VALUE", 0.0);
    }

    @Test
    void parsesDefBlobVector() throws Exception {
        IndiXmlCodec codec = new IndiXmlCodec();
        List<IndiProperty> props = codec.readAll(fixture("defBlobVector.xml"));
        IndiProperty.BlobVector b = (IndiProperty.BlobVector) props.getFirst();
        assertThat(b.name()).isEqualTo("CCD1");
        assertThat(b.bytes()).isNull();
    }

    @Test
    void parsesSetNumberVector() throws Exception {
        IndiXmlCodec codec = new IndiXmlCodec();
        List<IndiProperty> props = codec.readAll(fixture("setNumberVector.xml"));
        IndiProperty.NumberVector n = (IndiProperty.NumberVector) props.getFirst();
        assertThat(n.state()).isEqualTo(IndiProperty.State.OK);
        assertThat(n.elements()).containsEntry("CCD_EXPOSURE_VALUE", 0.0);
    }

    @Test
    void parsesSetBlobVector() throws Exception {
        IndiXmlCodec codec = new IndiXmlCodec();
        List<IndiProperty> props = codec.readAll(fixture("setBlobVector.xml"));
        IndiProperty.BlobVector b = (IndiProperty.BlobVector) props.getFirst();
        assertThat(b.bytes()).containsExactly(0x01, 0x02, 0x03);
        assertThat(b.format()).isEqualTo(".fits");
    }

    @Test
    void parsesConcatenatedFragments() throws Exception {
        IndiXmlCodec codec = new IndiXmlCodec();
        String concat = fixture("defSwitchVector.xml") + "\n" + fixture("defNumberVector.xml");
        List<IndiProperty> props = codec.readAll(concat);
        assertThat(props).hasSize(2);
    }

    @Test
    void parsesStreamIncrementally() throws Exception {
        IndiXmlCodec codec = new IndiXmlCodec();
        byte[] bytes = ("<root>"
                        + fixture("defSwitchVector.xml")
                        + fixture("defNumberVector.xml")
                        + "</root>")
                .getBytes(StandardCharsets.UTF_8);
        try (var in = new ByteArrayInputStream(bytes)) {
            List<IndiProperty> out = new java.util.ArrayList<>();
            codec.readStream(in, out::add);
            assertThat(out).hasSize(2);
        }
    }

    @Test
    void writesNewSwitchVector() throws Exception {
        IndiXmlCodec codec = new IndiXmlCodec();
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        codec.writeNewSwitchVector(out, "Telescope Simulator", "CONNECTION", Map.of("CONNECT", true, "DISCONNECT", false));
        String xml = out.toString(StandardCharsets.UTF_8);
        assertThat(xml)
                .contains("<newSwitchVector")
                .contains("device=\"Telescope Simulator\"")
                .contains("name=\"CONNECTION\"")
                .contains("<oneSwitch name=\"CONNECT\">On</oneSwitch>")
                .contains("<oneSwitch name=\"DISCONNECT\">Off</oneSwitch>");
    }

    @Test
    void writesNewNumberVector() throws Exception {
        IndiXmlCodec codec = new IndiXmlCodec();
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        codec.writeNewNumberVector(out, "CCD Simulator", "CCD_EXPOSURE", Map.of("CCD_EXPOSURE_VALUE", 5.0));
        String xml = out.toString(StandardCharsets.UTF_8);
        assertThat(xml)
                .contains("<newNumberVector")
                .contains("<oneNumber name=\"CCD_EXPOSURE_VALUE\">5.0</oneNumber>");
    }

    @Test
    void writesGetPropertiesAndEnableBlob() throws Exception {
        IndiXmlCodec codec = new IndiXmlCodec();
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        codec.writeGetProperties(out, null, null);
        assertThat(out.toString(StandardCharsets.UTF_8)).contains("<getProperties version=\"1.7\"/>");

        out.reset();
        codec.writeEnableBlob(out, "CCD Simulator", "Also");
        assertThat(out.toString(StandardCharsets.UTF_8))
                .contains("<enableBLOB device=\"CCD Simulator\">Also</enableBLOB>");
    }
}
