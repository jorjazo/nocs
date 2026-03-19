package dev.nocs.driver.efw;

import com.sun.jna.Library;
import com.sun.jna.Native;
import com.sun.jna.ptr.IntByReference;

/**
 * JNA bindings for ZWO EFW SDK (libEFWFilter).
 * See EFW_filter.h from ZWO/indi-3rdparty libasi.
 */
public interface EfwLib extends Library {

    int EFW_SUCCESS = 0;
    int EFW_ERROR_INVALID_INDEX = 1;
    int EFW_ERROR_INVALID_ID = 2;
    int EFW_ERROR_INVALID_VALUE = 3;
    int EFW_ERROR_REMOVED = 4;
    int EFW_ERROR_MOVING = 5;
    int EFW_ERROR_ERROR_STATE = 6;
    int EFW_ERROR_GENERAL_ERROR = 7;
    int EFW_ERROR_NOT_SUPPORTED = 8;
    int EFW_ERROR_CLOSED = 9;

    /** Position returned by EFWGetPosition while the wheel is still moving. */
    int EFW_IS_MOVING = -1;

    int EFWGetNum();

    int EFWGetID(int index, IntByReference id);

    int EFWOpen(int id);

    int EFWClose(int id);

    int EFWGetProperty(int id, EfwInfo.ByReference info);

    int EFWGetPosition(int id, IntByReference position);

    int EFWSetPosition(int id, int position);

    int EFWSetDirection(int id, boolean unidirectional);

    int EFWGetDirection(int id, IntByReference unidirectional);

    int EFWCalibrate(int id);

    String EFWGetSDKVersion();

    static EfwLib load(String libraryPath) {
        return Native.load(libraryPath, EfwLib.class);
    }
}
