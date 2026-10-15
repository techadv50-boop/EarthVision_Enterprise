# SATEYE Plugin-First Architecture

```mermaid
flowchart TB
  subgraph Host["Permanent Host Platform"]
    UI[Workspace layout / Map / Layers / Auth]
    PM[Plugin Manager]
    TT[Tool Tree Manager]
    SDK[Host SDK 1.1 sandboxed iframe]
    API[Backend API]
    Audit[Audit log]
  end

  subgraph Dyn["Dynamic Tool Platform"]
    Cat[(tool_categories DB)]
    Place[(tool_placements DB)]
    Packs[Signed plugin packages on tool_packs volume]
    Worker[Restricted plugin worker]
  end

  Admin -->|Create categories / upload / place / activate| TT
  TT --> Cat
  TT --> Place
  Admin -->|Install signed zip| PM
  PM --> Packs
  UI -->|GET /tools/tree| API
  API --> Cat
  API --> Place
  UI -->|Open tool| SDK
  SDK --> API
  API -->|authorized execute| Worker
  Worker --> Packs
  PM --> Audit
  TT --> Audit
```

## Layers

| Layer | Contains | Does not contain |
|-------|----------|------------------|
| **Host Platform** | Map, imagery, layers, auth, workspace, Plugin Manager, Tool Tree, Host SDK, security | Hardcoded analytical tool menus |
| **Dynamic Tool Platform** | Categories, placements, signed plugins, worker execution | Host React internals / tokens / Leaflet |

## Navigation vs execution

- **Navigation location:** category tree path (`tool_placements.category_id`)
- **Execution location:** UI slot (`tool_placements.execution_slot`)  
  Independent; change either without reinstalling.

## Empty install

`GET /api/v1/tools/tree` with no active placements returns:

> No tools installed. Create a category or upload your first tool.

Legacy 148-tool catalog remains in source (`frontend/src/toolbox/catalog.ts`, `tools/manifest.json`) but is **not** rendered.
