# Architecture

EarthVision Enterprise follows clean architecture with clear separation:

- **API layer** (`routers/`) — HTTP contracts, auth dependencies
- **Schemas** (`schemas/`) — Pydantic v2 request/response models
- **Services** (`services/`) — domain logic (catalog, analytics, ML, GIS)
- **Models** (`models/`) — SQLAlchemy ORM entities
- **Core** (`core/`) — config, security, DI, exceptions

Frontend uses CesiumJS for the globe, Zustand for client state, and Axios for the REST API.

The system is microservice-ready: catalog, analytics, raster, and auth can be extracted behind the same API gateway later.
