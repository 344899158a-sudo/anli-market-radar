from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "web"

PUBLIC_ASSETS = (
    "qqq.css",
    "watchlist_v2.css",
    "technical_advanced.css",
    "technical_simple.css",
    "decision_center.css",
    "watchlist_v2.js",
    "technical_advanced.js",
    "technical_simple.js",
    "decision_center.js",
    "qqq_trendiq.css",
    "qqq_trendiq.js",
    "v2_styles.css",
    "v2_app.js",
    "v3_styles.css",
    "v3_app.js",
    "v31_styles.css",
    "v31_app.js",
    "v32_styles.css",
    "v32_app.js",
    "checkin.css",
    "checkin.js",
    "public_adapter.js",
)

ROOT_ATTRIBUTE = re.compile(
    r'(?P<attribute>href|src|data-detail-href)="'
    r'/(?P<value>[^"]*)"'
)


def _public_html(source_name: str, *, adapter_before: str | None = None) -> str:
    text = (WEB_ROOT / source_name).read_text(encoding="utf-8")
    text = ROOT_ATTRIBUTE.sub(
        lambda match: (
            f'{match.group("attribute")}="./{match.group("value")}"'
        ),
        text,
    )
    if adapter_before:
        marker = f'<script src="./{adapter_before}'
        adapter = (
            '<script src="./public_adapter.js?v=20260811-public31"></script>\n'
        )
        if marker not in text:
            raise ValueError(
                f"{source_name} does not contain expected script {adapter_before}"
            )
        text = text.replace(marker, adapter + marker, 1)
    return text


def build_public_site(output_root: str | Path) -> Path:
    """Build the read-only Pages shell from the same responsive local UI."""

    output = Path(output_root).resolve()
    output.mkdir(parents=True, exist_ok=True)
    for asset_name in PUBLIC_ASSETS:
        source = WEB_ROOT / asset_name
        if not source.is_file():
            raise FileNotFoundError(source)
        shutil.copy2(source, output / asset_name)

    html_files = {
        "index.html": _public_html(
            "v32_index.html",
            adapter_before="v32_app.js",
        ),
        "v3.1.html": _public_html(
            "v31_index.html",
            adapter_before="v31_app.js",
        ),
        "v3.html": _public_html(
            "v3_index.html",
            adapter_before="v3_app.js",
        ),
        "v1.html": _public_html(
            "watchlist_v2.html",
            adapter_before="watchlist_v2.js",
        ),
        "qqq_trendiq.html": _public_html(
            "qqq_trendiq.html",
            adapter_before="qqq_trendiq.js",
        ),
        "playbooks.html": _public_html(
            "v2_index.html",
            adapter_before="v2_app.js",
        ),
        "checkin.html": _public_html("checkin.html"),
    }
    for target_name, content in html_files.items():
        (output / target_name).write_text(content, encoding="utf-8", newline="\n")

    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build the unified responsive ANLI public shell. "
            "Snapshot JSON must be exported separately into OUTPUT/data."
        )
    )
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = build_public_site(args.output)
    print(result)


if __name__ == "__main__":
    main()
