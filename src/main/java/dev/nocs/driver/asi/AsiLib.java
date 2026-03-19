package dev.nocs.driver.asi;

import com.sun.jna.Library;
import com.sun.jna.Native;
import com.sun.jna.NativeLong;
import com.sun.jna.Pointer;
import com.sun.jna.ptr.IntByReference;
import com.sun.jna.ptr.NativeLongByReference;

/**
 * JNA bindings for ZWO ASI Camera SDK (libASICamera2).
 * See ASICamera2.h from ZWO ASI_Camera_SDK.
 */
public interface AsiLib extends Library {

    // ASI_ERROR_CODE
    int ASI_SUCCESS = 0;
    int ASI_ERROR_INVALID_INDEX = 1;
    int ASI_ERROR_INVALID_ID = 2;
    int ASI_ERROR_INVALID_CONTROL_TYPE = 3;
    int ASI_ERROR_CAMERA_CLOSED = 4;
    int ASI_ERROR_CAMERA_REMOVED = 5;
    int ASI_ERROR_INVALID_PATH = 6;
    int ASI_ERROR_INVALID_FILEFORMAT = 7;
    int ASI_ERROR_INVALID_SIZE = 8;
    int ASI_ERROR_INVALID_IMGTYPE = 9;
    int ASI_ERROR_OUTOF_BOUNDARY = 10;
    int ASI_ERROR_TIMEOUT = 11;
    int ASI_ERROR_INVALID_SEQUENCE = 12;
    int ASI_ERROR_BUFFER_TOO_SMALL = 13;
    int ASI_ERROR_VIDEO_MODE_ACTIVE = 14;
    int ASI_ERROR_EXPOSURE_IN_PROGRESS = 15;
    int ASI_ERROR_GENERAL_ERROR = 16;

    // ASI_IMG_TYPE
    int ASI_IMG_RAW8 = 0;
    int ASI_IMG_RGB24 = 1;
    int ASI_IMG_RAW16 = 2;
    int ASI_IMG_Y8 = 3;
    int ASI_IMG_END = -1;

    // ASI_CONTROL_TYPE
    int ASI_GAIN = 0;
    int ASI_EXPOSURE = 1;
    int ASI_GAMMA = 2;
    int ASI_WB_R = 3;
    int ASI_WB_B = 4;
    int ASI_OFFSET = 5;
    int ASI_BANDWIDTHOVERLOAD = 6;
    int ASI_OVERCLOCK = 7;
    int ASI_TEMPERATURE = 8;
    int ASI_FLIP = 9;
    int ASI_AUTO_MAX_GAIN = 10;
    int ASI_AUTO_MAX_EXP = 11;
    int ASI_AUTO_TARGET_BRIGHTNESS = 12;
    int ASI_HARDWARE_BIN = 13;
    int ASI_HIGH_SPEED_MODE = 14;
    int ASI_COOLER_POWER_PERC = 15;
    int ASI_TARGET_TEMP = 16;
    int ASI_COOLER_ON = 17;
    int ASI_MONO_BIN = 18;
    int ASI_FAN_ON = 19;
    int ASI_PATTERN_ADJUST = 20;
    int ASI_ANTI_DEW_HEATER = 21;

    // ASI_EXPOSURE_STATUS
    int ASI_EXP_IDLE = 0;
    int ASI_EXP_WORKING = 1;
    int ASI_EXP_SUCCESS = 2;
    int ASI_EXP_FAILED = 3;

    // ASI_BOOL
    int ASI_FALSE = 0;
    int ASI_TRUE = 1;

    int ASIGetNumOfConnectedCameras();

    int ASIGetCameraProperty(AsiCameraInfo.ByReference pASICameraInfo, int iCameraIndex);

    int ASIOpenCamera(int iCameraID);

    int ASIInitCamera(int iCameraID);

    int ASICloseCamera(int iCameraID);

    int ASIGetNumOfControls(int iCameraID, IntByReference piNumberOfControls);

    int ASIGetControlValue(int iCameraID, int controlType, NativeLongByReference plValue, IntByReference pbAuto);

    int ASISetControlValue(int iCameraID, int controlType, NativeLong lValue, int bAuto);

    int ASISetROIFormat(int iCameraID, int iWidth, int iHeight, int iBin, int imgType);

    int ASIGetROIFormat(int iCameraID, IntByReference piWidth, IntByReference piHeight,
                        IntByReference piBin, IntByReference pImgType);

    int ASISetStartPos(int iCameraID, int iStartX, int iStartY);

    int ASIGetStartPos(int iCameraID, IntByReference piStartX, IntByReference piStartY);

    int ASIStartExposure(int iCameraID, int bIsDark);

    int ASIStopExposure(int iCameraID);

    int ASIGetExpStatus(int iCameraID, IntByReference pExpStatus);

    int ASIGetDataAfterExp(int iCameraID, Pointer pBuffer, NativeLong lBuffSize);

    String ASIGetSDKVersion();

    static AsiLib load(String libraryPath) {
        return Native.load(libraryPath, AsiLib.class);
    }
}
