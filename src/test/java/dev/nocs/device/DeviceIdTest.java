package dev.nocs.device;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assertions.assertThrows;

class DeviceIdTest {

    @Test
    void slugifiesIndiName() {
        assertThat(DeviceId.slug("Telescope Simulator").value()).isEqualTo("telescope-simulator");
        assertThat(DeviceId.slug("CCD_Simulator_1").value()).isEqualTo("ccd-simulator-1");
        assertThat(DeviceId.slug(" ZWO ASI294MC Pro ").value()).isEqualTo("zwo-asi294mc-pro");
    }

    @Test
    void rejectsEmpty() {
        assertThat(assertThrows(IllegalArgumentException.class, () -> DeviceId.slug("   ")).getMessage())
                .contains("blank");
    }
}
