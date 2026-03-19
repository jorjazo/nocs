package dev.nocs.driver.efw;

import com.sun.jna.Pointer;
import com.sun.jna.Structure;

/**
 * EFW_INFO struct from EFW_filter.h.
 */
@Structure.FieldOrder({"ID", "Name", "slotNum"})
public class EfwInfo extends Structure {

    public int ID;
    public byte[] Name = new byte[64];
    public int slotNum;

    public EfwInfo() {
        super();
    }

    public EfwInfo(Pointer p) {
        super(p);
        read();
    }

    public String getName() {
        int len = 0;
        while (len < Name.length && Name[len] != 0) len++;
        return new String(Name, 0, len);
    }

    public static class ByReference extends EfwInfo implements Structure.ByReference {}
}
