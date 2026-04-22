package dev.nocs.persistence;

import javax.sql.DataSource;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.jdbc.DataSourceBuilder;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Primary;

@Configuration
public class DataSourceConfig {

    @Bean
    @Primary
    DataSource dataSource(@Value("${nocs.datasource.url:jdbc:sqlite:file::memory:?cache=shared}") String url) {
        return DataSourceBuilder.create()
                .url(url)
                .driverClassName("org.sqlite.JDBC")
                .build();
    }
}
