package dev.nocs.driver.eaf;

import com.sun.jna.Pointer;
import com.sun.jna.Structure;

/**
 * EAF_INFO struct from EAF_focuser.h.
 */
@Structure.FieldOrder({"ID", "Name", "MaxStep"})
public class EafInfo extends Structure {

    public int ID;
    public byte[] Name = new byte[64];
    public int MaxStep;

    public EafInfo() {
        super();
    }

    public EafInfo(Pointer p) {
        super(p);
        read();
    }

    public String getName() {
        int len = 0;
        while (len < Name.length && Name[len] != 0) len++;
        return new String(Name, 0, len);
    }

    public static class ByReference extends EafInfo implements Structure.ByReference {}
}
