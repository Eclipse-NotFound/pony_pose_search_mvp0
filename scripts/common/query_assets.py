"""Query image ownership: never guess that a shared image belongs to a query."""
import json
from pathlib import Path


def query_image_destination(root, character_id, query_id):
    return str(Path(root) / "queries" / character_id / query_id / "query_input.png")


def resolve_query_image(root, character_id, query_id):
    destination = query_image_destination(root, character_id, query_id)
    if Path(destination).is_file():
        return destination
    record = Path(root) / "queries" / character_id / query_id / "query_keypoints.json"
    if record.is_file():
        try:
            declared = json.loads(record.read_text(encoding="utf-8")).get("query_image_path")
        except (OSError, ValueError):
            declared = None
        if declared:
            # Preserve an explicitly referenced legacy shared image. If it is
            # missing, return that path; do not fall back to another query.
            return str(Path(root) / declared)
    return destination
