# Kindle catalog and scriptlets

## Catalog facts

- On current Kindle firmware, `/var/local/cc.db` is an internal SQLite catalog, not normally exposed over USB. `Entries.p_uuid` identifies the row; `p_cdeKey` identifies the content; `p_location` distinguishes a downloaded book from a cloud-only row; `p_thumbnail` is the thumbnail path. Reading fields include `p_percentFinished`, `p_lastAccessedPosition`, and `p_readState`. Confirm the actual schema on each device before writing. [Observed schema](https://github.com/zevisvei/kindle-reading-dashboard/blob/main/docs/cc-db-schema.md).
- Cloud personal documents can have two `Entries` rows with the same `p_cdeKey`. Change only the downloaded `Entry:Item` `PDOC` KFX row with a non-null `p_location`. Match `p_uuid`, `p_cdeKey`, and the full `p_location`, and require the old `p_thumbnail` to be null. The code generator enforces these conditions.
- Some catalog indexes use `COLLATE icu`. A computer's stock SQLite may fail to query the database without registering that collation, and an invented collation makes `integrity_check` report spurious index mismatches. The helper scripts register one only for read queries; they never write the original catalog on the computer. The Kindle's own `sqlite3` may support its native collation; confirm with a read-only query before attempting an update.
- A live file copy can be inconsistent if SQLite is using a write-ahead log. Preserve the DB plus `-wal` and `-shm` when present for initial inspection. Before a write, the generated script uses SQLite `.backup` for a consistent snapshot. Never replace the live catalog file wholesale while Kindle services are using it.

## Read-only export probe

SH Integration indexes `.sh` files placed in `/mnt/us/documents` as library items; `# Name:` in the header sets the display title. [Scriptlet documentation](https://kindlemodding.org/kindle-dev/scriptlets.html). A minimal probe can be staged as `documents/Kindle Cover Check.sh`:

```sh
#!/bin/sh
# Name: Kindle Cover Check
# Author: Cover Repair
out=/mnt/us/KindleCoverCheck
mkdir -p "$out" || exit 1
cp /var/local/cc.db "$out/cc.db" || exit 1
for suffix in -wal -shm; do
  test ! -r "/var/local/cc.db$suffix" || cp "/var/local/cc.db$suffix" "$out/cc.db$suffix" || exit 1
done
command -v sqlite3 > "$out/sqlite-path.txt" 2>&1
echo complete > "$out/status.txt"
sync
```

The exported copy is for discovery. The repair script takes fresh before/after snapshots when it runs. If the launch entry does not appear, a leftover jailbreak folder is not proof that the current firmware still has a working hotfix. Do not install or rerun one without confirming model, firmware, compatibility, and authorization.

## Failure handling

- If precheck finds fewer rows than planned, the script stops before update. Re-export and investigate whether the Kindle changed its catalog or the chosen row was already repaired.
- The generated SQL uses one transaction and an assertion on the number of changed rows. SQLite `.bail on` closes and rolls back the transaction if the assertion fails. Check the actual `status.txt` and before/after snapshots anyway.
- If the SQL succeeds but a cover remains blank, first check that the referenced JPEG exists and opens, then let the Kindle refresh its library after USB disconnect. Avoid changing reading data to force a refresh.
- If `p_thumbnail` already points to a nonexistent file, preserve the path and restore a JPEG there when possible. The generator intentionally rejects these cases because they do not require a catalog update.
