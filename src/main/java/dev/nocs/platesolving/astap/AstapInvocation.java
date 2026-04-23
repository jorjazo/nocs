package dev.nocs.platesolving.astap;

import dev.nocs.platesolving.SolveOptions;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

public final class AstapInvocation {

    private AstapInvocation() {}

    public static List<String> command(AstapInstallation inst, Path fitsFile, SolveOptions opts) {
        List<String> cmd = new ArrayList<>();
        cmd.add(inst.binary().toString());
        cmd.add("-f");
        cmd.add(fitsFile.toString());
        cmd.add("-d");
        cmd.add(inst.dbDir().toString());
        cmd.add("-wcs");
        if (opts.raHintDeg() != null) {
            cmd.add("-ra");
            cmd.add(format(opts.raHintDeg() / 15.0));
        }
        if (opts.decHintDeg() != null) {
            cmd.add("-spd");
            cmd.add(format(opts.decHintDeg() + 90.0));
        }
        if (opts.radiusDeg() != null) {
            cmd.add("-r");
            cmd.add(format(opts.radiusDeg()));
        }
        return cmd;
    }

    private static String format(double v) {
        return String.format(Locale.ROOT, "%.10f", v).replaceAll("0+$", "").replaceAll("\\.$", ".0");
    }
}
