package dev.nocs.config;

import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.info.Contact;
import io.swagger.v3.oas.models.info.Info;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class OpenApiConfig {

    @Bean
    public OpenAPI nocsOpenAPI() {
        return new OpenAPI()
                .info(new Info()
                        .title("NOCS Observatory Control API")
                        .description("REST API for the NOCS Observatory Control System. Manages drivers, devices, and profiles.")
                        .version("0.1.0")
                        .contact(new Contact()
                                .name("NOCS")
                                .url("https://github.com/nocs")));
    }
}
