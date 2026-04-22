package dev.nocs;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.autoconfigure.jdbc.DataSourceAutoConfiguration;

@SpringBootApplication(exclude = {DataSourceAutoConfiguration.class})
public class NocsApplication {
    public static void main(String[] args) {
        SpringApplication.run(NocsApplication.class, args);
    }
}
