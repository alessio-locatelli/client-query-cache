from __future__ import annotations

from functools import cache
from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


@cache
def compose_mongodb_image(compose_file: Path) -> str:
    services = yaml.safe_load(compose_file.read_text(encoding="utf-8"))["services"]
    return str(services["mongo"]["image"])


MONGODB_IMAGE = compose_mongodb_image(REPOSITORY_ROOT / "docker-compose.yaml")
