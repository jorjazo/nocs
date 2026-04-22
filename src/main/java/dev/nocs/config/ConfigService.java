package dev.nocs.config;

import java.util.Map;
import org.springframework.stereotype.Service;

@Service
public class ConfigService {

    private final ConfigKvRepository repo;

    public ConfigService(ConfigKvRepository repo) {
        this.repo = repo;
    }

    public Map<String, String> getAll() {
        return repo.findAll();
    }

    public void updateAll(Map<String, String> changes) {
        changes.forEach(repo::upsert);
    }
}
