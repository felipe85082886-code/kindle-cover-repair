#!/usr/bin/env python3
"""Build a guarded Kindle scriptlet package for null catalog thumbnails."""

import argparse
import hashlib
import json
import os
import secrets
import shutil
import string
import tempfile
from pathlib import Path

from inspect_catalog import load_rows


def sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def jpeg_source(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size < 128:
        return False
    with path.open("rb") as stream:
        return stream.read(3) == b"\xff\xd8\xff"


def scriptlet(package_name: str, image_names: list[str], expected: int) -> str:
    image_checks = "\n".join(
        f'test -s "/mnt/us/system/thumbnails/{name}" || fail "Missing image: {name}"'
        for name in image_names
    )
    return f'''#!/bin/sh
# Name: Repair Kindle Covers
# Author: Cover Repair

set -u
pkg=/mnt/us/{package_name}
db=/var/local/cc.db
test ! -e "$pkg/status.txt" || exit 1
echo 'Starting cover repair' > "$pkg/status.txt" || exit 1
status="$pkg/status.txt"
fail() {{
  echo "$1" >> "$status"
  sync
  exit 1
}}
{image_checks}
test -r "$db" || fail 'Catalog unreadable; nothing changed'
command -v sqlite3 >/dev/null 2>&1 || fail 'SQLite unavailable; nothing changed'
sqlite3 "$db" ".backup '$pkg/before.db'" 2>> "$status" || fail 'Catalog backup failed; nothing changed'
test -s "$pkg/before.db" || fail 'Catalog backup empty; nothing changed'
sqlite3 "$db" < "$pkg/progress.sql" > "$pkg/progress.before.txt" 2>> "$status" || fail 'Progress snapshot failed; nothing changed'
matched=$(sqlite3 "$db" < "$pkg/precheck.sql" 2>> "$status") || fail 'Precheck query failed; nothing changed'
test "$matched" = {expected} || fail "Expected {expected} matching books, found $matched; nothing changed"
sqlite3 -batch "$db" < "$pkg/repair.sql" > "$pkg/sql-output.txt" 2>> "$status" || fail 'Update failed and was rolled back'
echo 'Catalog update committed' >> "$status"
sqlite3 "$db" < "$pkg/progress.sql" > "$pkg/progress.after.txt" 2>> "$status" || fail 'Progress verification query failed'
cmp -s "$pkg/progress.before.txt" "$pkg/progress.after.txt" || fail 'Progress values differ; inspect snapshots'
sqlite3 "$db" ".backup '$pkg/after.db'" 2>> "$status" || fail 'Updated, but final catalog export failed'
echo 'SUCCESS: covers linked; progress unchanged' >> "$status"
sync
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True, help="Exported cc.db copy")
    parser.add_argument("--plan", type=Path, required=True, help="JSON list of uuid and cover path")
    parser.add_argument("--output", type=Path, required=True, help="New staging directory")
    parser.add_argument("--kindle-root", type=Path, help="Mounted Kindle USB root for collision checks")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise ValueError(f"Output already exists: {output}")
    if args.kindle_root and (args.kindle_root / "documents/Repair Kindle Covers.sh").exists():
        raise ValueError("An earlier Repair Kindle Covers scriptlet is still on this Kindle; inspect and clean it first")
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    if not isinstance(plan, list) or not 1 <= len(plan) <= 50:
        raise ValueError("Plan must be a list of 1 to 50 books")
    rows = {row["p_uuid"]: row for row in load_rows(args.catalog)}
    seen_uuids = set()
    selected = []
    for entry in plan:
        if not isinstance(entry, dict) or not isinstance(entry.get("uuid"), str) or not isinstance(entry.get("cover"), str):
            raise ValueError("Every plan entry needs string uuid and cover fields")
        uuid = entry["uuid"]
        if uuid in seen_uuids or uuid not in rows:
            raise ValueError(f"Duplicate or non-downloaded KFX UUID: {uuid}")
        seen_uuids.add(uuid)
        row = rows[uuid]
        if row["p_thumbnail"] is not None:
            raise ValueError(f"Thumbnail path already set for {uuid}; inspect the file instead")
        source = Path(entry["cover"]).expanduser().resolve()
        if not jpeg_source(source):
            raise ValueError(f"Not a readable JPEG: {source}")
        if args.kindle_root:
            location = row["p_location"]
            if not location.startswith("/mnt/us/"):
                raise ValueError(f"Unexpected book location: {location}")
            book = args.kindle_root / location.removeprefix("/mnt/us/")
            if not book.is_file():
                raise ValueError(f"Book is not readable on USB: {book}")
        selected.append((row, source, entry.get("source_url")))

    run_id = secrets.token_hex(4)
    package_name = f"KindleCoverRepair-{run_id}"
    if args.kindle_root and (args.kindle_root / package_name).exists():
        raise ValueError("Generated package folder already exists on this Kindle")
    alphabet = string.ascii_letters + string.digits
    used_names = set()
    changes = []
    for row, source, source_url in selected:
        while True:
            token = "".join(secrets.choice(alphabet) for _ in range(6))
            name = f"thumbnail_{token}.jpg"
            target = args.kindle_root / "system/thumbnails" / name if args.kindle_root else None
            if name not in used_names and (target is None or not target.exists()):
                used_names.add(name)
                break
        changes.append({
            "uuid": row["p_uuid"],
            "cde_key": row["p_cdeKey"],
            "location": row["p_location"],
            "title": row["p_titles_0_nominal"],
            "thumbnail": f"/mnt/us/system/thumbnails/{name}",
            "cover_sha256": sha256(source),
            "source_cover": str(source),
            "source_url": source_url,
        })

    guards = [
        f"(p_uuid={sql_quote(x['uuid'])} AND p_cdeKey={sql_quote(x['cde_key'])} "
        f"AND p_location={sql_quote(x['location'])})"
        for x in changes
    ]
    where = "p_type='Entry:Item' AND p_cdeType='PDOC' AND p_thumbnail IS NULL AND (" + " OR ".join(guards) + ")"
    keys = ",".join(sql_quote(x["uuid"]) for x in changes)
    progress_sql = (
        "SELECT p_uuid || '|' || quote(p_percentFinished) || '|' || "
        "quote(p_lastAccessedPosition) || '|' || quote(p_readState) || '|' || "
        "quote(p_lastAccess) || '|' || quote(p_lastOpenTime) "
        f"FROM Entries WHERE p_uuid IN ({keys}) ORDER BY p_uuid;\n"
    )
    case = "\n".join(
        f"  WHEN {sql_quote(x['uuid'])} THEN {sql_quote(x['thumbnail'])}"
        for x in changes
    )
    repair_sql = (
        ".bail on\nPRAGMA busy_timeout=5000;\n"
        f"CREATE TEMP TABLE assert_count (n INTEGER CHECK(n={len(changes)}));\n"
        "BEGIN IMMEDIATE;\n"
        f"UPDATE Entries SET p_thumbnail=CASE p_uuid\n{case}\nEND WHERE {where};\n"
        "INSERT INTO assert_count VALUES(changes());\nCOMMIT;\n"
    )
    manifest = {
        "run_id": run_id,
        "package_name": package_name,
        "scriptlet": "documents/Repair Kindle Covers.sh",
        "changes": changes,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".kindle-cover-", dir=output.parent))
    try:
        package = temporary / package_name
        thumbnails = temporary / "system/thumbnails"
        documents = temporary / "documents"
        package.mkdir()
        thumbnails.mkdir(parents=True)
        documents.mkdir()
        for change, (_, source, _) in zip(changes, selected):
            shutil.copy2(source, thumbnails / Path(change["thumbnail"]).name)
        (package / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (package / "precheck.sql").write_text(f"SELECT count(*) FROM Entries WHERE {where};\n", encoding="utf-8")
        (package / "progress.sql").write_text(progress_sql, encoding="utf-8")
        (package / "repair.sql").write_text(repair_sql, encoding="utf-8")
        (documents / "Repair Kindle Covers.sh").write_text(
            scriptlet(package_name, [Path(x["thumbnail"]).name for x in changes], len(changes)), encoding="utf-8"
        )
        os.chmod(documents / "Repair Kindle Covers.sh", 0o755)
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    print(output / package_name / "manifest.json")


if __name__ == "__main__":
    main()
