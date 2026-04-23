package dev.nocs.platesolving;

import java.sql.ResultSet;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.time.format.DateTimeParseException;
import java.util.List;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

@Repository
public class PlateSolutionRepository {

    private final JdbcTemplate jdbc;

    public PlateSolutionRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public void upsert(PlateSolutionRecord rec) {
        jdbc.update(
                "INSERT INTO plate_solutions("
                        + "image_id, ra_j2000_deg, dec_j2000_deg, pixel_scale_arcsec_per_px, "
                        + "rotation_deg, field_width_deg, field_height_deg, duration_ms, "
                        + "solver, solved_at) "
                        + "VALUES(?,?,?,?,?,?,?,?,?,?) "
                        + "ON CONFLICT(image_id) DO UPDATE SET "
                        + "ra_j2000_deg=excluded.ra_j2000_deg, "
                        + "dec_j2000_deg=excluded.dec_j2000_deg, "
                        + "pixel_scale_arcsec_per_px=excluded.pixel_scale_arcsec_per_px, "
                        + "rotation_deg=excluded.rotation_deg, "
                        + "field_width_deg=excluded.field_width_deg, "
                        + "field_height_deg=excluded.field_height_deg, "
                        + "duration_ms=excluded.duration_ms, "
                        + "solver=excluded.solver, "
                        + "solved_at=excluded.solved_at",
                rec.imageId(),
                rec.raJ2000Deg(), rec.decJ2000Deg(), rec.pixelScaleArcsecPerPx(),
                rec.rotationDeg(), rec.fieldWidthDeg(), rec.fieldHeightDeg(),
                rec.durationMs(),
                rec.solver(),
                rec.solvedAt().toString());
    }

    public Optional<PlateSolutionRecord> findByImageId(long imageId) {
        List<PlateSolutionRecord> rows = jdbc.query(
                "SELECT id, image_id, ra_j2000_deg, dec_j2000_deg, pixel_scale_arcsec_per_px, "
                        + "rotation_deg, field_width_deg, field_height_deg, duration_ms, solver, "
                        + "solved_at FROM plate_solutions WHERE image_id = ?",
                MAPPER, imageId);
        return rows.isEmpty() ? Optional.empty() : Optional.of(rows.get(0));
    }

    public boolean deleteByImageId(long imageId) {
        return jdbc.update("DELETE FROM plate_solutions WHERE image_id = ?", imageId) > 0;
    }

    private static final RowMapper<PlateSolutionRecord> MAPPER = (ResultSet rs, int n) -> {
        String solvedAt = rs.getString("solved_at");
        Instant when = parseSolvedAt(solvedAt);
        return new PlateSolutionRecord(
                rs.getLong("id"),
                rs.getLong("image_id"),
                rs.getDouble("ra_j2000_deg"),
                rs.getDouble("dec_j2000_deg"),
                rs.getDouble("pixel_scale_arcsec_per_px"),
                rs.getDouble("rotation_deg"),
                rs.getDouble("field_width_deg"),
                rs.getDouble("field_height_deg"),
                rs.getLong("duration_ms"),
                rs.getString("solver"),
                when);
    };

    private static Instant parseSolvedAt(String s) {
        if (s == null) {
            return null;
        }
        try {
            return Instant.parse(s);
        } catch (DateTimeParseException e) {
            return LocalDateTime.parse(s.replace(' ', 'T')).toInstant(ZoneOffset.UTC);
        }
    }
}
