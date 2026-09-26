#!/usr/bin/env python3
"""Verify that a Kindle cover repair changed only planned thumbnail paths."""

import argparse
import collections
import hashlib
import json
from pathlib import Path

from inspect_catalog import open_catalog


def rows_by_uuid(db, table: str) -> tuple[list[str], dict]:
    columns = [row[1] for row in db.execute(f"PRAGMA table_info({table})")]
    if "p_uuid" not in columns:
        raise ValueError("Entries has no p_uuid column")
    rows = [tuple(row) for row in db.execute(f"SELECT * FROM {table}")]
    uuids = [row[columns.index("p_uuid")] for row in rows]
    if len(uuids) != len(set(uuids)):
        raise ValueError("Duplicate UUIDs in Entries")
    return columns, dict(zip(uuids, rows))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True, help="Device scriptlet status.txt")
    parser.add_argument("--kindle-root", type=Path, help="Mounted Kindle USB root")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    changes = {item["uuid"]: item for item in manifest["changes"]}
    if not changes or len(changes) != len(manifest["changes"]):
        raise ValueError("Manifest has no changes or duplicate UUIDs")
    status = args.status.read_text(encoding="utf-8")
    if not status.strip().splitlines() or status.strip().splitlines()[-1] != "SUCCESS: covers linked; progress unchanged":
        raise ValueError("Device did not report a complete successful repair")

    with open_catalog(args.before) as before, open_catalog(args.after) as after:
        before_tables = {row[0] for row in before.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )}
        after_tables = {row[0] for row in after.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )}
        if before_tables != after_tables:
            raise ValueError("Catalog table set changed")
        for table in sorted(before_tables - {"Entries"}):
            old = collections.Counter(tuple(row) for row in before.execute(f"SELECT * FROM {table}"))
            new = collections.Counter(tuple(row) for row in after.execute(f"SELECT * FROM {table}"))
            if old != new:
                raise ValueError(f"Unplanned changes in table {table}")
        old_columns, old_rows = rows_by_uuid(before, "Entries")
        new_columns, new_rows = rows_by_uuid(after, "Entries")
        if old_columns != new_columns or old_rows.keys() != new_rows.keys():
            raise ValueError("Entries schema or row identity changed")
        thumb_index = old_columns.index("p_thumbnail")
        key_index = old_columns.index("p_cdeKey")
        location_index = old_columns.index("p_location")
        changed = set()
        for uuid, old in old_rows.items():
            new = new_rows[uuid]
            if old == new:
                continue
            if uuid not in changes:
                raise ValueError(f"Unplanned entry changed: {uuid}")
            expected = changes[uuid]
            if (old[thumb_index] is not None or new[thumb_index] != expected["thumbnail"]
                    or old[key_index] != expected["cde_key"]
                    or old[location_index] != expected["location"]):
                raise ValueError(f"Wrong cover target or book identity: {uuid}")
            differing = [i for i, pair in enumerate(zip(old, new)) if pair[0] != pair[1]]
            if differing != [thumb_index]:
                raise ValueError(f"Other fields changed for {uuid}: {[old_columns[i] for i in differing]}")
            changed.add(uuid)
        if changed != changes.keys():
            raise ValueError(f"Not all planned books changed: {sorted(changes.keys() - changed)}")

    if args.kindle_root:
        for item in changes.values():
            relative = item["thumbnail"].removeprefix("/mnt/us/")
            if relative == item["thumbnail"]:
                raise ValueError("Thumbnail is not on USB storage")
            image = args.kindle_root / relative
            if not image.is_file() or sha256(image) != item["cover_sha256"]:
                raise ValueError(f"Thumbnail absent or hash mismatch: {image}")
    print(f"Verified {len(changes)} cover changes; all other catalog fields and tables unchanged")


if __name__ == "__main__":
    main()
