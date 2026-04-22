package dev.nocs;

import dev.nocs.bootstrap.DataDirBootstrap;
import dev.nocs.bootstrap.TokenBootstrap;
import java.nio.file.Path;
import java.util.Properties;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.autoconfigure.jdbc.DataSourceAutoConfiguration;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;

@SpringBootApplication(exclude = {DataSourceAutoConfiguration.class})
@ConfigurationPropertiesScan
public class NocsApplication {

    public static void main(String[] args) throws Exception {
        Path dataDir = DataDirBootstrap.resolveDataDir();
        Path configFile = DataDirBootstrap.ensureLayout(dataDir);
        String token = TokenBootstrap.ensureToken(configFile);

        System.out.println("NOCS data dir: " + dataDir);
        System.out.println("NOCS bearer token: " + token);

        Properties props = new Properties();
        props.setProperty("spring.config.additional-location", "file:" + configFile);
        props.setProperty("nocs.datasource.url", "jdbc:sqlite:file:" + dataDir.resolve("nocs.sqlite"));

        SpringApplication app = new SpringApplication(NocsApplication.class);
        app.setDefaultProperties(props);
        app.run(args);
    }
}
