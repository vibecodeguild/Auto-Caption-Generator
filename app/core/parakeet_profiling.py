"""Extract execution evidence from ONNX Runtime's per-session profiles."""
import json


def executed_providers(paths):
    providers = set()
    for path in paths:
        try:
            events = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # ORT sessions created in the same second can collide on a profile
            # filename. Damaged profiles are not execution evidence. Only
            # complete, parseable profiles can establish an executed provider.
            continue
        providers.update(event.get("args", {}).get("provider") for event in events
                         if event.get("args", {}).get("provider"))
    return providers
