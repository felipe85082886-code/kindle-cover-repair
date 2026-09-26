#!/usr/bin/env python3
"""List downloaded personal KFX books and their catalog thumbnail state."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from urllib.parse import quote


def open_catalog(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise ValueError(f"Catalog not found: {path}")
    uri = "file:" + quote(str(path.resolve()), safe="/") + "?mode=ro"
    db = sqlite3.connect(uri, uri=True)
    # Read-only queries need this registered on hosts without Kindle's ICU build.
    db.create_collation("icu", lambda a, b: (a > b) - (a < b))
    db.row_factory = sqlite3.Row
    return db


def load_rows(path: Path) -> list[dict]:
    with open_catalog(path) as db:
        required = {
            "p_uuid", "p_type", "p_cdeKey", "p_cdeType", "p_location",
            "p_titles_0_nominal", "p_thumbnail", "p_percentFinished",
            "p_lastAccessedPosition", "p_readState",
        }
        columns = {row[1] for row in db.execute("PRAGMA table_info(Entries)")}
        missing = required - columns
        if missing:
            raise ValueError(f"Unsupported Entries schema; missing: {sorted(missing)}")
        rows = db.execute(
            "SELECT p_uuid,p_type,p_cdeKey,p_cdeType,p_location,"
            "p_titles_0_nominal,p_thumbnail,p_percentFinished,"
            "p_lastAccessedPosition,p_readState FROM Entries"
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        location = item["p_location"]
        if (item["p_type"] == "Entry:Item" and item["p_cdeType"] == "PDOC"
                and isinstance(location, str) and location.lower().endswith(".kfx")):
            result.append(item)
    return sorted(result, key=lambda item: (item["p_titles_0_nominal"] or "", item["p_uuid"]))


def thumbnail_state(item: dict, kindle_root: Path | None) -> str:
    thumb = item["p_thumbnail"]
    if not thumb:
        return "missing_catalog_path"
    if kindle_root is None:
        return "linked_unchecked"
    if not thumb.startswith("/mnt/us/"):
        return "non_usb_path"
    target = kindle_root / thumb.removeprefix("/mnt/us/")
    return "linked" if target.is_file() and target.stat().st_size > 0 else "missing_file"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog", type=Path, help="Exported cc.db copy")
    parser.add_argument("--kindle-root", type=Path, help="Mounted Kindle USB root")
    parser.add_argument("--problems-only", action="store_true")
    args = parser.parse_args()
    output = []
    for item in load_rows(args.catalog):
        state = thumbnail_state(item, args.kindle_root)
        if args.problems_only and state in ("linked", "linked_unchecked"):
            continue
        output.append({
            "uuid": item["p_uuid"],
            "title": item["p_titles_0_nominal"],
            "cde_key": item["p_cdeKey"],
            "location": item["p_location"],
            "thumbnail": item["p_thumbnail"],
            "state": state,
            "percent_finished": item["p_percentFinished"],
            "last_accessed_position": item["p_lastAccessedPosition"],
            "read_state": item["p_readState"],
        })
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
