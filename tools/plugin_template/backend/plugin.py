"""Template plugin backend — runs only inside the restricted worker."""

def run_synthetic(context: dict) -> dict:
    return {
        "kind": "template_demo",
        "plugin_id": context.get("plugin_id"),
        "message": "Replace run_synthetic with your analysis.",
        "note": "No access to Host secrets or Leaflet.",
    }
