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
| `viewer/data/*` | Viewer/webmod PNG + JSON exports | Yes, from a pack via `export-viewer` | optional in archive |
| Game-side installs (`Mods/RealEarth`, GeneratedWorlds copies) | Mod DLL, config, installed world/pack copies | Yes: `make install`, install scripts | not backed up (regenerable) |
| Save games (`$USERDATA/Saves`) | Stock game saves | No, but owned by the stock game (see BackupMod notes in GAP_HARMONY_MODLETS) | test harness moves old saves to `Saves_trash` with a 7 day window instead of deleting |
| `<Managed>/Assembly-CSharp.dll.re_stock_bak` | Stock engine DLL pre-expand | Recoverable twice over: the backup file itself, plus Steam Verify regenerating stock bytes | see [GAME_VERSION](GAME_VERSION.md) |

The terrarium cache matters most for the remote-data-loss disaster: with it,
every pack and world stays rebuildable even if the AWS dataset changes or
disappears. Without it, rebuilds depend on a third party staying alive.

## RPO / RTO per disaster

| Disaster | Without this repo's tooling | With tooling used |
|---|---|---|
| Repo disk dies | Total loss of all worlds and packs; RPO infinite | RPO = last archive copied off-host; RTO = minutes (`artifacts-restore`) |
| AWS Terrarium dataset vanishes | Packs unreproducible; every future rebuild silently degrades to synthetic fallback | No impact while `data/cache/terrarium` is present (and archived) |
| Bad bake overwrites a good world | Gone; `worlds/` has no history | Restore last archive, or re-bake offline from pack + cache |
| Engine expand corrupts the game DLL | Game will not start | `make engine-restore` (or Steam Verify); RTO = minutes |
| Harness run pointed at real userdata deletes saves | Permanent loss | `Saves_trash/<timestamp>` window, 7 days default (`RE_SAVE_TRASH_DAYS`) |

RPO statement: unbounded until an operator runs `make artifacts-backup`. The
repo ships no scheduler; treat "archive after each bake worth keeping" as the
operating rule below.

## Procedures

Back up (writes a checksum-verified archive, warns when it lands on the same
disk as the data):

```bash
make artifacts-backup                          # into <repo>/backups (git-ignored)
RE_BACKUP_DIR=/mnt/external make artifacts-backup   # straight onto other storage
```

Restore:

```bash
make artifacts-restore ARCHIVE=backups/realearth-artifacts-20260826T120000.tar.gz
RE_FORCE_RESTORE=1 make artifacts-restore ARCHIVE=...   # move existing dirs aside first
```

The script verifies the gzip stream and sha256 before declaring success, and
refuses corrupt archives or silent overwrite on restore. A zero-byte or
truncated archive fails the command instead of passing quietly.

### Restore drill

A backup that has never been restored is a hypothesis. Prove the whole path
on synthetic state (no real artifacts touched) any time:

```bash
make artifacts-drill
```

The drill builds a sandbox tree shaped like real state, backs it up, destroys
the artifacts, restores, and compares every file byte-for-byte. It also
asserts the guardrails: clobber is refused without `RE_FORCE_RESTORE=1`, a
forced restore moves the old tree aside instead of deleting it, and a corrupt
archive is refused with nothing extracted. CI runs it on every change to keep
the claim current (`scripts/artifacts_drill.sh`).

Engine DLL recovery is separate and already scripted: `make engine-restore`,
`make engine-verify` (drift detection against the sha256 recorded at expand
time). See [HEIGHT_LIMITS](HEIGHT_LIMITS.md) and [THREAT_MODEL](THREAT_MODEL.md).

## Operating rules

1. After any bake worth keeping (`make bake`, `height-map`, `bake-world`):
   `make artifacts-backup`, then copy the archive off-host. Same-disk archives
   do not survive instance loss.
2. Include `data/cache/` in whatever off-host copy you make: it is the only
   hedge against losing the upstream tile dataset.
3. Restores are destructive-by-default-proof: they refuse to clobber; use
   `RE_FORCE_RESTORE=1` when you mean it (current dirs are moved aside, not
   deleted).

## Open questions (evidence outside this repo)

- Is any off-host copy target configured or scheduled for this machine?
  Nothing in the repo says so; absent evidence, assume no. Until one exists,
  the RPO for repo-disk loss is however long an operator waits between
  `make artifacts-backup` and the off-host copy.
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

- **2026-08-26:** Registered as durability posture hub (state inventory, RPO/RTO, procedures, drill).
