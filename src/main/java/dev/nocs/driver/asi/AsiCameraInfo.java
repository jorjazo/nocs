package dev.nocs.driver.asi;

import com.sun.jna.NativeLong;
import com.sun.jna.Pointer;
import com.sun.jna.Structure;

/**
 * JNA mapping for ASI_CAMERA_INFO struct from ASICamera2.h.
 * Uses NativeLong for C 'long' fields (8 bytes on Linux x64).
 */
@Structure.FieldOrder({
        "Name", "CameraID", "MaxHeight", "MaxWidth",
        "IsColorCam", "BayerPattern",
        "SupportedBins", "SupportedVideoFormat",
        "PixelSize", "MechanicalShutter", "ST4Port",
        "IsCoolerCam", "IsUSB3Host", "IsUSB3Camera",
        "ElecPerADU", "BitDepth", "IsTriggerCam", "Unused"
})
public class AsiCameraInfo extends Structure {

    public byte[] Name = new byte[64];
    public int CameraID;
    public NativeLong MaxHeight = new NativeLong();
    public NativeLong MaxWidth = new NativeLong();
    public int IsColorCam;
    public int BayerPattern;
    public int[] SupportedBins = new int[16];
    public int[] SupportedVideoFormat = new int[8];
    public double PixelSize;
    public int MechanicalShutter;
    public int ST4Port;
    public int IsCoolerCam;
    public int IsUSB3Host;
    public int IsUSB3Camera;
    public float ElecPerADU;
    public int BitDepth;
    public int IsTriggerCam;
    public byte[] Unused = new byte[16];

    public AsiCameraInfo() {
        super();
    }

    public AsiCameraInfo(Pointer p) {
        super(p);
        read();
    }

    public String getName() {
        int len = 0;
        while (len < Name.length && Name[len] != 0) len++;
        return new String(Name, 0, len);
    }

    public int getMaxWidth() {
        return MaxWidth.intValue();
    }

    public int getMaxHeight() {
        return MaxHeight.intValue();
    }

    public boolean isCoolerCam() {
        return IsCoolerCam != 0;
    }

    public static class ByReference extends AsiCameraInfo implements Structure.ByReference {}
}
