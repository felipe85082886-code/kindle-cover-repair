# Kindle Cover Repair

A Codex skill for diagnosing and repairing blank Kindle library covers on existing personal documents, with checks that protect reading progress.

The workflow is designed for a specific failure seen on downloaded KFX personal documents: the cover image exists or can be supplied, but the downloaded book's `Entries.p_thumbnail` value in the Kindle's internal `cc.db` catalog is empty. It identifies the exact book entry, backs up the catalog, changes only that thumbnail association, and compares before and after snapshots. It does not delete or resend the book.

## Install

Copy this repository into your Codex skills directory as `kindle-cover-repair`:

```sh
git clone https://github.com/felipe85082886-code/kindle-cover-repair.git ~/.codex/skills/kindle-cover-repair
```

Then ask Codex to repair a missing Kindle cover, or invoke `$kindle-cover-repair` explicitly.

## What the skill includes

- `SKILL.md`: diagnosis, backup, repair, and verification workflow.
- `scripts/inspect_catalog.py`: read-only inspection of downloaded PDOC KFX catalog entries.
- `scripts/build_repair.py`: produces a guarded device-side repair script and staged thumbnails.
- `scripts/verify_repair.py`: checks the catalog diff and thumbnail hashes after the device run.
- `references/catalog-and-scriptlets.md`: catalog notes and a read-only export probe.

Python 3.9 or newer is required for the helper scripts. No third-party Python packages are required.

## Scope and cautions

The internal catalog is normally unavailable over USB. The catalog workflow requires a compatible, already-authorized device-side script launcher and user interaction on the Kindle. Do not install a jailbreak or system launcher solely by following this repository. Confirm the device model, firmware, catalog schema, target book, and cover image before preparing a repair. Keep catalog exports, reading-progress data, book files, and generated manifests private; they can contain personal information and are intentionally absent from this repository.

This is an independent community workflow and is not affiliated with Amazon or OpenAI. Device software and catalog schemas can change, so each repair requires fresh checks and an on-screen confirmation.
