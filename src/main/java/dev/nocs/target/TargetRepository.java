package dev.nocs.target;

import java.sql.ResultSet;
import java.sql.Statement;
import java.util.List;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.stereotype.Repository;

@Repository
public class TargetRepository {

    private final JdbcTemplate jdbc;

    public TargetRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    private static final RowMapper<Target> MAPPER = (ResultSet rs, int rowNum) -> new Target(
            "custom:" + rs.getLong("id"),
            rs.getString("name"),
            List.of(),
            TargetKind.parseOrOther(rs.getString("kind")),
            rs.getDouble("ra_j2000_deg"),
            rs.getDouble("dec_j2000_deg"),
            "",
            Double.NaN,
            Double.NaN,
            rs.getString("notes"));

    public long insert(String name, double ra, double dec, TargetKind kind, String notes) {
        GeneratedKeyHolder key = new GeneratedKeyHolder();
        jdbc.update(con -> {
            var ps = con.prepareStatement(
                    "INSERT INTO targets_custom(name, ra_j2000_deg, dec_j2000_deg, kind, notes) VALUES(?, ?, ?, ?, ?)",
                    Statement.RETURN_GENERATED_KEYS);
            ps.setString(1, name);
            ps.setDouble(2, ra);
            ps.setDouble(3, dec);
            ps.setString(4, kind.name());
            ps.setString(5, notes == null ? "" : notes);
            return ps;
        }, key);
        return key.getKey().longValue();
    }

    public List<Target> findAll() {
        return jdbc.query(
                "SELECT id, name, ra_j2000_deg, dec_j2000_deg, kind, notes FROM targets_custom ORDER BY id DESC",
                MAPPER);
    }

    public Optional<Target> findById(long id) {
        return jdbc.query(
                "SELECT id, name, ra_j2000_deg, dec_j2000_deg, kind, notes FROM targets_custom WHERE id = ?",
                MAPPER, id).stream().findFirst();
    }

    public boolean delete(long id) {
        return jdbc.update("DELETE FROM targets_custom WHERE id = ?", id) > 0;
    }
}
