from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AppConfig:
    path: Path
    raw: dict[str, Any]

    @property
    def symbols(self) -> list[str]: return [item["symbol"].upper() for item in self.raw["symbols"]]
    @property
    def symbol_meta(self) -> dict[str, dict[str, Any]]: return {item["symbol"].upper(): item for item in self.raw["symbols"]}
    @property
    def rules(self) -> dict[str, Any]: return self.raw["rules"]
    @property
    def sector_benchmarks(self) -> dict[str, str]: return self.raw["sector_benchmarks"]
    def get(self, key: str, default: Any = None) -> Any: return self.raw.get(key, default)


def load_config(path: str | Path) -> AppConfig:
    path = Path(path).resolve(); data = json.loads(path.read_text(encoding="utf-8-sig"))
    symbols = data.get("symbols", [])
    if len(symbols) != 48 or len({item["symbol"] for item in symbols}) != 48:
        raise ValueError("截图关注池必须包含48个唯一代码")
    return AppConfig(path=path, raw=data)
