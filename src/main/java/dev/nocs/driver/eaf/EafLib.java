package dev.nocs.driver.eaf;

import com.sun.jna.Library;
import com.sun.jna.Native;
import com.sun.jna.ptr.IntByReference;

/**
 * JNA bindings for ZWO EAF SDK (libEAFFocuser).
 * See EAF_focuser.h from ZWO/indi-3rdparty libasi.
 */
public interface EafLib extends Library {

    int EAF_SUCCESS = 0;
    int EAF_ERROR_INVALID_INDEX = 1;
    int EAF_ERROR_INVALID_ID = 2;
    int EAF_ERROR_INVALID_VALUE = 3;
    int EAF_ERROR_REMOVED = 4;
    int EAF_ERROR_MOVING = 5;
    int EAF_ERROR_ERROR_STATE = 6;
    int EAF_ERROR_GENERAL_ERROR = 7;
    int EAF_ERROR_NOT_SUPPORTED = 8;
    int EAF_ERROR_CLOSED = 9;

    int EAFGetNum();

    int EAFGetID(int index, IntByReference id);

    int EAFOpen(int id);

    int EAFClose(int id);

    int EAFGetProperty(int id, EafInfo.ByReference info);

    int EAFMove(int id, int step);

    int EAFStop(int id);

    int EAFIsMoving(int id, IntByReference moving, IntByReference handControl);

    int EAFGetPosition(int id, IntByReference position);

    int EAFGetTemp(int id, float[] temp);

    int EAFGetMaxStep(int id, IntByReference maxStep);

    int EAFSetMaxStep(int id, int maxStep);

    int EAFCheck(int vid, int pid);

    static EafLib load(String libraryPath) {
        return Native.load(libraryPath, EafLib.class);
    }
}
