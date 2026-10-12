from __future__ import annotations

import json
import os
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent


def load_dotenv(path: Path | None = None) -> None:
    env_path = path or (PROJECT_ROOT / ".env")
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


def default_config_path() -> Path:
    cwd_config = Path.cwd() / "config.json"
    if cwd_config.exists():
        return cwd_config
    return PROJECT_ROOT / "config.json"


def load_config(path: Path | None = None) -> dict:
    load_dotenv()
    config_path = Path(path) if path else default_config_path()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["_config_path"] = str(config_path.resolve())
    root = config_path.resolve().parent
    config["_root"] = str(root)
    _apply_env(config)
    return config


def project_path(config: dict, key: str) -> Path:
    root = Path(config["_root"])
    return root / config[key]


def _apply_env(config: dict) -> None:
    ollama = config.setdefault("ollama", {})
    if os.getenv("OLLAMA_HOST"):
        ollama["host"] = os.environ["OLLAMA_HOST"]
    if os.getenv("OLLAMA_MODEL"):
        ollama["model"] = os.environ["OLLAMA_MODEL"]
    if os.getenv("OLLAMA_ENABLED"):
        ollama["enabled"] = os.environ["OLLAMA_ENABLED"].strip().lower() in {"1", "true", "yes", "on"}

    email = config.setdefault("email", {})
    mapping = {
        "SMTP_HOST": "smtp_host",
        "SMTP_USER": "smtp_user",
        "SMTP_FROM": "smtp_from",
        "EMAIL_TO": "to",
    }
    for env_name, field in mapping.items():
        if os.getenv(env_name):
            email[field] = os.environ[env_name]
    if os.getenv("SMTP_PORT"):
        email["smtp_port"] = int(os.environ["SMTP_PORT"])
    if os.getenv("SMTP_TLS"):
        email["use_tls"] = os.environ["SMTP_TLS"].strip().lower() in {"1", "true", "yes", "on"}
    if email.get("smtp_host") and email.get("to"):
        email["enabled"] = True
