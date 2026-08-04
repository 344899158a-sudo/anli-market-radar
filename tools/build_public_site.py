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
    "watchlist_v2.js",
    "technical_advanced.js",
    "technical_simple.js",
    "qqq_trendiq.css",
    "qqq_trendiq.js",
    "public_adapter.js",
)

ROOT_ATTRIBUTE = re.compile(
    r'(?P<attribute>href|src|data-detail-href)="'
    r'/(?P<value>[^"]*)"'
)


PUBLIC_DISCIPLINE_PATTERNS = (
    (
        "decision center stylesheet",
        re.compile(
            r'^[ \t]*<link[^>]+href="/decision_center\.css[^"]*"[^>]*>\r?\n?',
            re.MULTILINE,
        ),
    ),
    (
        "discipline check-in link",
        re.compile(
            r'^[ \t]*<a class="checkin-link"[^>]*>.*?</a>\r?\n?',
            re.MULTILINE,
        ),
    ),
    (
        "discipline mobile navigation link",
        re.compile(
            r'^[ \t]*<a href="#decisionCenter"[^>]*>.*?</a>\r?\n?',
            re.MULTILINE,
        ),
    ),
    (
        "today discipline section",
        re.compile(
            r'^[ \t]*<section id="decisionCenter"[^>]*>.*?</section>\r?\n?',
            re.MULTILINE | re.DOTALL,
        ),
    ),
    (
        "decision center script",
        re.compile(
            r'^[ \t]*<script src="/decision_center\.js[^"]*"></script>\r?\n?',
            re.MULTILINE,
        ),
    ),
)


def _without_public_discipline(text: str) -> str:
    for label, pattern in PUBLIC_DISCIPLINE_PATTERNS:
        text, count = pattern.subn("", text, count=1)
        if count != 1:
            raise ValueError(f"public shell is missing expected {label}")
    return text


def _public_html(
    source_name: str,
    *,
    adapter_before: str | None = None,
    remove_discipline: bool = False,
) -> str:
    text = (WEB_ROOT / source_name).read_text(encoding="utf-8")
    if remove_discipline:
        text = _without_public_discipline(text)
    text = ROOT_ATTRIBUTE.sub(
        lambda match: (
            f'{match.group("attribute")}="./{match.group("value")}"'
        ),
        text,
    )
    if adapter_before:
        marker = f'<script src="./{adapter_before}'
        adapter = (
            '<script src="./public_adapter.js?v=20260731-public1"></script>\n'
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
            "watchlist_v2.html",
            adapter_before="watchlist_v2.js",
            remove_discipline=True,
        ),
        "qqq_trendiq.html": _public_html(
            "qqq_trendiq.html",
            adapter_before="qqq_trendiq.js",
        ),
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
