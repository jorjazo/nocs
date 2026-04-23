package dev.nocs.image;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.stereotype.Repository;

@Repository
public class ImageRepository {

    private final JdbcTemplate jdbc;

    public ImageRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public long insert(ImageRecord rec) {
        GeneratedKeyHolder key = new GeneratedKeyHolder();
        jdbc.update(con -> {
            var ps = con.prepareStatement(
                    "INSERT INTO images(session_id, device_id, filter, target, exposure_s, "
                            + "step_name, seq_index, fits_path, thumb_path, bytes, width, height, "
                            + "bitpix, date_obs) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    Statement.RETURN_GENERATED_KEYS);
            if (rec.sessionId() == null) {
                ps.setNull(1, java.sql.Types.INTEGER);
            } else {
                ps.setLong(1, rec.sessionId());
            }
            ps.setString(2, rec.deviceId());
            ps.setString(3, rec.filter());
            ps.setString(4, rec.target());
            ps.setDouble(5, rec.exposureSec());
            ps.setString(6, rec.stepName());
            ps.setInt(7, rec.seqIndex());
            ps.setString(8, rec.fitsPath());
            if (rec.thumbPath() == null) {
                ps.setNull(9, java.sql.Types.VARCHAR);
            } else {
                ps.setString(9, rec.thumbPath());
            }
            ps.setLong(10, rec.bytes());
            setNullableInt(ps, 11, rec.width());
            setNullableInt(ps, 12, rec.height());
            setNullableInt(ps, 13, rec.bitpix());
            if (rec.dateObs() == null) {
                ps.setNull(14, java.sql.Types.VARCHAR);
            } else {
                ps.setString(14, rec.dateObs());
            }
            return ps;
        }, key);
        return Objects.requireNonNull(key.getKey()).longValue();
    }

    public Optional<ImageRecord> findById(long id) {
        List<ImageRecord> out = jdbc.query(
                "SELECT id, session_id, device_id, filter, target, exposure_s, step_name, "
                        + "seq_index, fits_path, thumb_path, bytes, width, height, bitpix, date_obs, "
                        + "created_at FROM images WHERE id = ?",
                MAPPER, id);
        return out.isEmpty() ? Optional.empty() : Optional.of(out.get(0));
    }

    public List<ImageRecord> list(Filters filters) {
        StringBuilder sql = new StringBuilder(
                "SELECT id, session_id, device_id, filter, target, exposure_s, step_name, "
                        + "seq_index, fits_path, thumb_path, bytes, width, height, bitpix, date_obs, "
                        + "created_at FROM images WHERE 1=1");
        List<Object> args = new ArrayList<>();
        if (filters.deviceId() != null) {
            sql.append(" AND device_id = ?");
            args.add(filters.deviceId());
        }
        if (filters.sessionId() != null) {
            sql.append(" AND session_id = ?");
            args.add(filters.sessionId());
        }
        if (filters.target() != null) {
            sql.append(" AND target = ?");
            args.add(filters.target());
        }
        if (filters.filter() != null) {
            sql.append(" AND filter = ?");
            args.add(filters.filter());
        }
        sql.append(" ORDER BY id DESC LIMIT ? OFFSET ?");
        args.add(filters.limit());
        args.add(filters.offset());
        return jdbc.query(sql.toString(), MAPPER, args.toArray());
    }

    public boolean delete(long id) {
        return jdbc.update("DELETE FROM images WHERE id = ?", id) > 0;
    }

    public int updateBytes(long id, long bytes) {
        return jdbc.update("UPDATE images SET bytes = ? WHERE id = ?", bytes, id);
    }

    private static void setNullableInt(java.sql.PreparedStatement ps, int idx, Integer value) throws SQLException {
        if (value == null) {
            ps.setNull(idx, java.sql.Types.INTEGER);
        } else {
            ps.setInt(idx, value);
        }
    }

    private static final RowMapper<ImageRecord> MAPPER = (ResultSet rs, int rowNum) -> {
        Long sessionId = rs.getObject("session_id") == null ? null : rs.getLong("session_id");
        Integer width = rs.getObject("width") == null ? null : rs.getInt("width");
        Integer height = rs.getObject("height") == null ? null : rs.getInt("height");
        Integer bitpix = rs.getObject("bitpix") == null ? null : rs.getInt("bitpix");
        String createdAt = rs.getString("created_at");
        Instant created = createdAt == null
                ? null
                : LocalDateTime.parse(createdAt.replace(' ', 'T')).toInstant(ZoneOffset.UTC);
        return new ImageRecord(
                rs.getLong("id"),
                sessionId,
                rs.getString("device_id"),
                rs.getString("filter"),
                rs.getString("target"),
                rs.getDouble("exposure_s"),
                rs.getString("step_name"),
                rs.getInt("seq_index"),
                rs.getString("fits_path"),
                rs.getString("thumb_path"),
                rs.getLong("bytes"),
                width,
                height,
                bitpix,
                rs.getString("date_obs"),
                created);
    };

    public record Filters(
            String deviceId,
            Long sessionId,
            String target,
            String filter,
            int limit,
            int offset) {

        public Filters {
            if (limit <= 0 || limit > 1000) {
                limit = 100;
            }
            if (offset < 0) {
                offset = 0;
            }
        }
    }
}
