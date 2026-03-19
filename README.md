# NOCS Observatory Control System

Spring Boot REST API for observatory equipment control.

## Run

```bash
./gradlew bootRun
```

## ZWO EAF (Electronic Auto Focuser)

Shipped libs are in `native/linux-x64/` (libEAFFocuser.bin, libudev.so.1). No system libudev required when shipped.

**Run with EAF support:**
```bash
./run.sh
```
Or `./gradlew bootRun` (auto-configures when `native/linux-x64/libEAFFocuser.bin` exists).

**To refresh shipped libs** (e.g. after cloning without native/):
```bash
./gradlew copyLibudev
EAF_SDK_SOURCE=/path/to/indi-3rdparty/libasi/x64 ./gradlew copyEafSdk
```

**Profile**: Create a profile with driver ID `dev.nocs.driver.eaf.EafDriver` in `driverIds`, then load and `POST /api/v1/focuser/connect`.

**EAF load test:**
```bash
./gradlew test --tests EafDriverLoadTest
```

## API Documentation

- **Swagger UI** (explorer): http://localhost:8080/api/v1/swagger-ui.html
- **OpenAPI spec (JSON)**: http://localhost:8080/api/v1/v3/api-docs

Export the spec to a file:
```bash
curl -s http://localhost:8080/api/v1/v3/api-docs > openapi.json
```
