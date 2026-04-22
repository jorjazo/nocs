package dev.nocs.observatory;

import java.sql.ResultSet;
import java.sql.Statement;
import java.util.List;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.stereotype.Repository;

@Repository
public class ObservatoryRepository {

    private final JdbcTemplate jdbc;

    public ObservatoryRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    private static final RowMapper<Observatory> MAPPER = (ResultSet rs, int rowNum) ->
            new Observatory(
                    rs.getLong("id"),
                    rs.getString("name"),
                    rs.getDouble("latitude_deg"),
                    rs.getDouble("longitude_deg"),
                    rs.getDouble("elevation_m"),
                    rs.getString("timezone"),
                    rs.getString("horizon_mask_json"),
                    rs.getInt("is_active") == 1);

    public long insert(
            String name, double lat, double lon, double elev, String tz, String horizonMaskJson, boolean active) {
        GeneratedKeyHolder key = new GeneratedKeyHolder();
        jdbc.update(con -> {
            var ps = con.prepareStatement(
                    "INSERT INTO observatories(name, latitude_deg, longitude_deg, elevation_m, timezone, horizon_mask_json, is_active) "
                            + "VALUES(?, ?, ?, ?, ?, ?, ?)",
                    Statement.RETURN_GENERATED_KEYS);
            ps.setString(1, name);
            ps.setDouble(2, lat);
            ps.setDouble(3, lon);
            ps.setDouble(4, elev);
            ps.setString(5, tz);
            ps.setString(6, horizonMaskJson);
            ps.setInt(7, active ? 1 : 0);
            return ps;
        }, key);
        return key.getKey().longValue();
    }

    public List<Observatory> findAll() {
        return jdbc.query(
                "SELECT id, name, latitude_deg, longitude_deg, elevation_m, timezone, horizon_mask_json, is_active "
                        + "FROM observatories ORDER BY id",
                MAPPER);
    }

    public Optional<Observatory> findById(long id) {
        return jdbc.query(
                        "SELECT id, name, latitude_deg, longitude_deg, elevation_m, timezone, horizon_mask_json, is_active "
                                + "FROM observatories WHERE id = ?",
                        MAPPER,
                        id)
                .stream()
                .findFirst();
    }

    public Optional<Observatory> findActive() {
        return jdbc.query(
                        "SELECT id, name, latitude_deg, longitude_deg, elevation_m, timezone, horizon_mask_json, is_active "
                                + "FROM observatories WHERE is_active = 1",
                        MAPPER)
                .stream()
                .findFirst();
    }

    public void deactivateAll() {
        jdbc.update("UPDATE observatories SET is_active = 0, updated_at = datetime('now')");
    }

    public void activate(long id) {
        jdbc.update("UPDATE observatories SET is_active = 1, updated_at = datetime('now') WHERE id = ?", id);
    }

    public void update(long id, String name, double lat, double lon, double elev, String tz, String horizonMaskJson) {
        jdbc.update(
                "UPDATE observatories SET name=?, latitude_deg=?, longitude_deg=?, elevation_m=?, timezone=?, horizon_mask_json=?, updated_at=datetime('now') "
                        + "WHERE id=?",
                name,
                lat,
                lon,
                elev,
                tz,
                horizonMaskJson,
                id);
    }

    public void delete(long id) {
        jdbc.update("DELETE FROM observatories WHERE id = ?", id);
    }
}
