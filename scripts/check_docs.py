"""Validate local Markdown links and requirement traceability, without network access."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
REQ = re.compile(r"\b(?:FR|NFR)-\d{3}\b")
CATALOG = ROOT / "docs/01-requirements/product-requirements.md"
TRACE = ROOT / "docs/01-requirements/traceability.md"


def main() -> int:
    failures = []
    documents = [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]
    # The upstream README is an archival source, not our maintained specification.
    documents = [p for p in documents if "upstream" not in p.relative_to(ROOT).parts]
    for path in documents:
        text = path.read_text(encoding="utf-8")
        text = re.sub(r"```.*?```", "", text, flags=re.S)
        for match in LINK.finditer(text):
            target = match.group(1).strip("<>")
            if target.startswith(("#", "http:", "https:", "mailto:", "file:")):
                continue
            target = unquote(target.split("#", 1)[0])
            if target and not (path.parent / target).exists():
                failures.append(f"{path.relative_to(ROOT)}: missing link target {target}")
    if not CATALOG.exists() or not TRACE.exists():
        failures.append("Requirement catalog and traceability matrix must both exist")
    else:
        catalog = set(REQ.findall(CATALOG.read_text(encoding="utf-8")))
        trace = set(REQ.findall(TRACE.read_text(encoding="utf-8")))
        if not catalog:
            failures.append("Requirement catalog is empty")
        if catalog != trace:
            failures.append(f"Requirement coverage mismatch: {sorted(catalog ^ trace)}")
        for path in documents:
            unknown = set(REQ.findall(path.read_text(encoding="utf-8"))) - catalog
            if unknown:
                failures.append(f"{path.relative_to(ROOT)}: unknown requirements {sorted(unknown)}")
    for failure in failures:
        print(failure, file=sys.stderr)
    if failures:
        return 1
    print(f"Documentation OK: {len(documents)} documents, local links and requirement coverage")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
