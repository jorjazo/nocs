# NOCS Observatory Control System

Spring Boot REST API for observatory equipment control.

## Run

```bash
./gradlew bootRun
```

## API Documentation

- **Swagger UI** (explorer): http://localhost:8080/api/v1/swagger-ui.html
- **OpenAPI spec (JSON)**: http://localhost:8080/api/v1/v3/api-docs

Export the spec to a file:
```bash
curl -s http://localhost:8080/api/v1/v3/api-docs > openapi.json
```
