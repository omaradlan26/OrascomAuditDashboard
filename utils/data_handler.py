from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA_FILE = BASE_DIR / "data" / "observations.json"


def get_data_file() -> Path:
    configured_path = os.getenv("OBSERVATIONS_DATA_FILE")
    return Path(configured_path).expanduser() if configured_path else DEFAULT_DATA_FILE


def get_storage_status() -> dict[str, str | bool]:
    inline_data = os.getenv("OBSERVATIONS_DATA_JSON")
    data_file = get_data_file()

    if inline_data:
        return {
            "label": "Environment JSON",
            "read_only": True,
            "detail": "Loaded from OBSERVATIONS_DATA_JSON.",
        }

    if os.getenv("VERCEL"):
        return {
            "label": "Bundled JSON file",
            "read_only": True,
            "detail": "Vercel deployments need external persistent storage for write operations.",
        }

    return {
        "label": "Local JSON file",
        "read_only": False,
        "detail": f"Loaded from {data_file}.",
    }


def load_data() -> dict[str, list[dict[str, Any]]]:
    inline_data = os.getenv("OBSERVATIONS_DATA_JSON")
    if inline_data:
        try:
            data = json.loads(inline_data)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    data_file = get_data_file()
    if not data_file.exists():
        return {}

    try:
        with data_file.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (json.JSONDecodeError, OSError):
        return {}

    return data if isinstance(data, dict) else {}


def save_data(data: dict[str, list[dict[str, Any]]]) -> None:
    storage = get_storage_status()
    if storage["read_only"]:
        raise RuntimeError("Cannot save data while the application is in read-only mode.")

    data_file = get_data_file()
    data_file.parent.mkdir(parents=True, exist_ok=True)
    with data_file.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)


def get_assignment_names(data: dict[str, list[dict[str, Any]]]) -> list[str]:
    return sorted(data.keys())


def get_next_id(observations: list[dict[str, Any]]) -> int:
    if not observations:
        return 1
    return max(int(item.get("id", 0)) for item in observations) + 1


def renumber_observations(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for index, item in enumerate(observations, start=1):
        item["id"] = index
    return observations
