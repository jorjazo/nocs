package dev.nocs.session;

import java.time.Instant;

public record Session(long id, String name, Instant openedAt, Instant closedAt, String logPath) {}
