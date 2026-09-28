# Backup and restore (durability posture)

**Owns:** what generated state can be lost, what backs it up, how to get it back, RPO/RTO statements.
**Not:** data source policy ([DATA_SOURCES](DATA_SOURCES.md)), threat model ([THREAT_MODEL](THREAT_MODEL.md)).

Everything expensive in this repo is git-ignored: `worlds/`, `data/samples/`,
`data/cache/`, `viewer/data/`. CI uploads none of it
(`.github/workflows/release.yml` intentionally builds no archive). A lost
workstation therefore loses every baked world and tile pack unless archives
exist elsewhere.

---

## State inventory and coverage

| State | Contents | Rebuildable without network? | Backed up by |
|---|---|---|---|
| `worlds/*` | Baked GeneratedWorlds: `dtm.raw`, `dtm_processed.raw`, `splat3/4*`, `biomes.png`, `prefabs.xml`, `main.ttw`, `checksums.txt` | No. Needs the tile pack plus a local game install for the `main.ttw` template | `make artifacts-backup` |
| `data/samples/*` | Tile packs: `.rte` tiles + `earth.manifest.json` (+ height-test previews) | No. Needs Terrarium tiles (or user-held GeoTIFF) | `make artifacts-backup` |
| `data/cache/terrarium` | Raw AWS Terrarium source tiles (`RE_TERRARIUM_CACHE`, set by the Makefile). Fetched once, reused forever | Yes, once populated: packs rebuild offline from cached tiles | `make artifacts-backup` |
| `viewer/data/*` | Viewer/webmod PNG + JSON exports | Yes, from a pack via `export-viewer` | `make artifacts-backup` (always, when present) |
| `GeneratedWorlds/<name>` (client + dedicated) | Installed world copy, possibly hand-edited or generated with other settings | From `worlds/` only if the repo copy still matches | not archived by default; an install that changes the world moves the previous tree to `GeneratedWorlds_trash/<UTC stamp>__<name>` (`scripts/generated-world.sh`), an install of an unchanged world copies nothing. Both can be added with `RE_BACKUP_EXTRA_PATHS` |
| Game-side installs (`Mods/RealEarth`, GeneratedWorlds copies) | Mod DLL, config, installed world/pack copies | Yes: `make install`, install scripts | not backed up (regenerable) |
| Save games (`$USERDATA/Saves`) | Stock game saves | No. The one genuinely irreplaceable state in this product | **not covered by default.** `RE_BACKUP_EXTRA_PATHS=saves=$USERDATA/Saves`. The test harness only moves old saves to `Saves_trash` with a 7 day window, and prunes that window on the next run |
| `<Managed>/Assembly-CSharp.dll` | Stock engine DLL | Always recoverable: Steam Verify regenerates it, and the mod never writes it | see [GAME_VERSION](GAME_VERSION.md) |

The terrarium cache matters most for the remote-data-loss disaster: with it,
every pack and world stays rebuildable even if the AWS dataset changes or
disappears. Without it, rebuilds depend on a third party staying alive.

The state above is everything `ARTIFACT_DIRS` covers, and it is all
repo-relative. State that lives *outside* the repo (save games, installed
worlds, install trash) is outside the archive unless an operator names it
explicitly; see [Out-of-tree state](#out-of-tree-state). Nothing in this repo
schedules that, so the RPO for save games is unbounded until someone wires it
up and says so.

## RPO / RTO per disaster

| Disaster | Without this repo's tooling | With tooling used |
|---|---|---|
| Repo disk dies | Total loss of all worlds and packs; RPO infinite | RPO = last archive copied off-host; RTO = minutes (`artifacts-restore`) |
| Server disk dies with player saves on it | Permanent loss of every save; no other copy exists anywhere | Only if `RE_BACKUP_EXTRA_PATHS` named `Saves`. Unnamed, this is a total loss, not an RPO |
| AWS Terrarium dataset vanishes | Packs unreproducible; every future rebuild silently degrades to synthetic fallback | No impact while `data/cache/terrarium` is present (and archived) |
| Bad bake overwrites a good world | Gone; `worlds/` has no history | Bakes never overwrite in place: the previous tree is renamed `<world>.pre-bake-<UTC stamp>` next to it (delete it once happy). Fallback: last archive or re-bake offline from pack + cache |
| Game update breaks the runtime YDim patch | `heightMode=stock`, peaks clamp ~250 | Rebuild against the new DLL (`make install`/`make build`); no backup to restore because no DLL is edited |
| Harness run pointed at real userdata deletes saves | Permanent loss | `Saves_trash/<timestamp>` window, 7 days default (`RE_SAVE_TRASH_DAYS`) |
| Install overwrites a hand-edited `GeneratedWorlds` world | Permanent loss of edits no archive holds | Previous world kept at `GeneratedWorlds_trash/<UTC stamp>__<name>`, pruned after `RE_WORLD_TRASH_DAYS` (default 14) |
| Backup disk fills (the cache is tens of GB and every run is another full copy) | Later backups fail; if the failure is unnoticed, the only surviving archives are old | `RE_BACKUP_KEEP=N` prunes to the newest N, and only after the new archive passes its checksum gate |

RPO statement: unbounded until an operator runs `make artifacts-backup`. The
repo ships no scheduler; treat "archive after each bake worth keeping" as the
operating rule below, and `make artifacts-status` as the check that the rule
was followed.

## Procedures

Back up (writes a checksum-verified archive, warns when it lands on the same
disk as the data):

```bash
make artifacts-backup                          # into <repo>/backups (git-ignored)
RE_BACKUP_DIR=/mnt/external make artifacts-backup   # straight onto other storage
RE_BACKUP_KEEP=5 make artifacts-backup         # prune to the newest 5 afterwards
```

Restore:

```bash
make artifacts-restore ARCHIVE=backups/realearth-artifacts-20260826T120000.tar.gz
RE_FORCE_RESTORE=1 make artifacts-restore ARCHIVE=...   # move existing dirs aside first
```

The script verifies the gzip stream and sha256 before declaring success, and
refuses corrupt archives or silent overwrite on restore. A zero-byte or
truncated archive fails the command instead of passing quietly.

`RE_BACKUP_KEEP` defaults to 0 (keep everything). Pruning runs only after the
new archive has been written and checksum-verified, so a failed or full-disk
backup never removes the last good one.

### Out-of-tree state

Save games, installed `GeneratedWorlds`, and the install trash live outside
the repo and are **not** in an archive unless named. `RE_BACKUP_EXTRA_PATHS`
takes newline-separated `label=/absolute/path` entries:

```bash
RE_BACKUP_EXTRA_PATHS="saves=$USERDATA/Saves" \
RE_BACKUP_DIR=/mnt/external make artifacts-backup
```

Each entry is stored under `realearth-extra/<label>/` in the archive with the
absolute target path recorded beside the bytes, so a restore puts it back
exactly where it came from rather than guessing. A path that does not exist
**fails the backup**: a typo must not produce an archive that claims to hold
your saves and does not. Restores follow the same refuse-clobber rule as the
in-repo dirs, and `RE_FORCE_RESTORE=1` moves an existing target to
`<target>.pre-restore-<UTC stamp>` rather than deleting it.

The point of this is the RPO. `Saves_trash` keeps a moved-aside save for
`RE_SAVE_TRASH_DAYS` (default 7) and then deletes it, so without a named
extra path the only copy of a save is one harness run away from gone.

Check the durability net before you need it:

```bash
make artifacts-status                                   # age + checksum of the newest archive
RE_BACKUP_MAX_AGE_DAYS=1 make artifacts-status          # tighter freshness limit
```

`artifacts-status` exits nonzero when no archive exists, when the newest is
older than `RE_BACKUP_MAX_AGE_DAYS` (default 7), or when its checksum no
longer matches. It warns when the archive directory shares the repo disk.
Nothing schedules backups, so this is the only evidence of freshness.

### Restore drill

A backup that has never been restored is a hypothesis. Prove the whole path
on synthetic state (no real artifacts touched) any time:

```bash
make artifacts-drill
```

The drill builds a sandbox tree shaped like real state, backs it up, destroys
the artifacts, restores, and compares every file byte-for-byte. It also
asserts the guardrails: clobber is refused without `RE_FORCE_RESTORE=1`, a
forced restore moves the old tree aside instead of deleting it, a corrupt
archive is refused with nothing extracted, `artifacts-status` fails on a
missing or tampered archive, installing a world into `GeneratedWorlds` moves
the previous tree to `GeneratedWorlds_trash` with its contents intact, a second
install of the same world is a no-op, an out-of-tree tree round-trips through
destroy and restore back to its recorded absolute path, a nonexistent extra
path fails the backup, and `RE_BACKUP_KEEP` leaves exactly N archives. CI runs
it on every change to keep the claim current (`scripts/artifacts_drill.sh`).

Engine DLL recovery is no longer needed for height: the YDim expand is
hot-patched at boot (no DLL is edited), so a game update at worst needs
`make install` to re-apply the mod. See [HEIGHT_LIMITS](HEIGHT_LIMITS.md) and
[THREAT_MODEL](THREAT_MODEL.md).

## Operating rules

1. After any bake worth keeping (`make bake`, `height-map`, `bake-world`):
   `make artifacts-backup`, then copy the archive off-host. Same-disk archives
   do not survive instance loss.
2. Include `data/cache/` in whatever off-host copy you make: it is the only
   hedge against losing the upstream tile dataset. If you relocate it via
   `RE_TERRARIUM_CACHE`, `artifacts-backup` warns that the archive no longer
   contains it; copy the relocated cache into your off-host set yourself.
3. Restores are destructive-by-default-proof: they refuse to clobber; use
   `RE_FORCE_RESTORE=1` when you mean it (current dirs are moved aside, not
   deleted). Bakes get the same treatment automatically: rebaking onto an
   existing output moves that output to `<name>.pre-bake-<stamp>` instead of
   overwriting it.
4. Installs never delete a world either. `install_height_pack.sh`,
   `install_proton.sh`, and the dedicated harnesses copy through
   `install_generated_world` (`scripts/generated-world.sh`), which renames the
   installed `GeneratedWorlds/<name>` to
   `GeneratedWorlds_trash/<UTC stamp>__<name>` before writing the new one.
   An install of a world that is already in place copies nothing, so a rerun
   neither re-copies the world nor adds a trash entry. Trash entries older
   than `RE_WORLD_TRASH_DAYS` (default 14, `0` prunes on the next run) are
   removed by the next install of that world; newer ones are yours to delete
   once the new world is what you want.
5. On a dedicated server, name the state that lives outside the repo before
   you need it: `RE_BACKUP_EXTRA_PATHS="saves=$USERDATA/Saves"`. A save
   game's only other copy is the `Saves_trash` window, and that window closes.

## Open questions (evidence outside this repo)

- Is any off-host copy target configured or scheduled for this machine?
  Nothing in the repo says so; absent evidence, assume no. Until one exists,
  the RPO for repo-disk loss is however long an operator waits between
  `make artifacts-backup` and the off-host copy.
- Is `RE_BACKUP_EXTRA_PATHS` set anywhere on a real deployment? Nothing in
  the repo says so, and the tooling ships no default, so absent evidence every
  save game is one `Saves_trash` prune from gone.
- The artifact backup/restore roundtrip is proven by `make artifacts-drill`
  and re-proven on every CI run. Not yet drilled against real multi-gigabyte
  baked state, nor is the engine expand/restore pair (needs a game install;
  TODO.md tracks both).

## Related docs

| Doc | Role |
|---|---|
| [DATA_SOURCES](DATA_SOURCES.md) | Source policy for rebuildable inputs |
| [THREAT_MODEL](THREAT_MODEL.md) | Attack surface around artifacts and installs |
| [HEIGHT_LIMITS](HEIGHT_LIMITS.md) | Engine DLL backup/restore discipline |

## Changelog

- **2026-09-28:** `RE_BACKUP_EXTRA_PATHS` archives and restores state outside the repo (saves, installed worlds) and `RE_BACKUP_KEEP` bounds the archive set; both drilled in CI.
- **2026-09-28:** World installs move the previous `GeneratedWorlds` tree aside instead of deleting it; `artifacts-status` reports archive age and checksum.
- **2026-08-26:** Registered as durability posture hub (state inventory, RPO/RTO, procedures, drill).
