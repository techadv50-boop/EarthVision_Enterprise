# Architecture

SAT EYE follows clean architecture with clear separation:

- **API layer** (`routers/`) — HTTP contracts, auth dependencies
- **Schemas** (`schemas/`) — Pydantic v2 request/response models
- **Services** (`services/`) — domain logic (catalog, analytics, ML, GIS)
- **Models** (`models/`) — SQLAlchemy ORM entities
- **Core** (`core/`) — config, security, DI, exceptions

## Frontend (Eye In Sky)

The primary UI is a three-step workflow optimized for slow networks:

1. Place selection (search or map click)
2. Recent satellite scenes (20)
3. Spectral index analysis on the selected scene

Mapping uses **Leaflet + OSM tiles** instead of CesiumJS to minimize download size and GPU cost.
