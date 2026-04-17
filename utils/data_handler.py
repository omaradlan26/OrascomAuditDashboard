from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from typing import Any


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA_FILE = BASE_DIR / "data" / "observations.json"
DEFAULT_KV_KEY = "orascom_audit_dashboard:observations"


def get_data_file() -> Path:
    configured_path = os.getenv("OBSERVATIONS_DATA_FILE")
    return Path(configured_path).expanduser() if configured_path else DEFAULT_DATA_FILE


def get_kv_config() -> dict[str, str] | None:
    api_url = os.getenv("KV_REST_API_URL")
    api_token = os.getenv("KV_REST_API_TOKEN")
    if api_url and api_token:
        return {
            "url": api_url.rstrip("/"),
            "token": api_token,
            "key": os.getenv("OBSERVATIONS_KV_KEY", DEFAULT_KV_KEY),
        }
    return None


def get_storage_status() -> dict[str, str | bool]:
    inline_data = os.getenv("OBSERVATIONS_DATA_JSON")
    data_file = get_data_file()
    kv_config = get_kv_config()

    if kv_config:
        return {
            "label": "Vercel KV",
            "read_only": False,
            "detail": f"Loaded from KV key {kv_config['key']}.",
        }

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
    kv_config = get_kv_config()
    if kv_config:
        return load_kv_data(kv_config)

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


def load_seed_data() -> dict[str, list[dict[str, Any]]]:
    data_file = DEFAULT_DATA_FILE
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

    kv_config = get_kv_config()
    if kv_config:
        save_kv_data(kv_config, data)
        return

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


def load_kv_data(config: dict[str, str]) -> dict[str, list[dict[str, Any]]]:
    try:
        response = kv_request(config, "GET", f"get/{config['key']}")
    except RuntimeError:
        return {}

    value = response.get("result")
    if not value:
        return {}

    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def save_kv_data(config: dict[str, str], data: dict[str, list[dict[str, Any]]]) -> None:
    payload = json.dumps(data)
    kv_request(config, "POST", "set", {"key": config["key"], "value": payload})


def kv_request(
    config: dict[str, str],
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    request = Request(
        url=f"{config['url']}/{path}",
        method=method,
        data=payload,
        headers={
            "Authorization": f"Bearer {config['token']}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=10) as response:
            raw_response = response.read().decode("utf-8")
    except (HTTPError, URLError) as exc:
        raise RuntimeError("KV request failed.") from exc

    try:
        parsed = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise RuntimeError("KV response was not valid JSON.") from exc

    if parsed.get("error"):
        raise RuntimeError(f"KV error: {parsed['error']}")

    return parsed
