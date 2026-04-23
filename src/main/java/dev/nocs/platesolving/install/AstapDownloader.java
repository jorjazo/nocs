package dev.nocs.platesolving.install;

import java.io.IOException;
import java.net.URI;
import java.nio.file.Path;

public interface AstapDownloader {
    void download(URI url, Path dest, ProgressListener listener) throws IOException;
}
