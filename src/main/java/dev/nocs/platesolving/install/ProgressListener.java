package dev.nocs.platesolving.install;

@FunctionalInterface
public interface ProgressListener {
    void onBytes(long bytesDone, long bytesTotal);
}
