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
| `GeneratedWorlds/<name>` (client + dedicated) | Installed world copy, possibly hand-edited or generated with other settings | From `worlds/` only if the repo copy still matches | not archived; every install moves the previous tree to `GeneratedWorlds_trash/<UTC stamp>__<name>` (`scripts/generated-world.sh`) |
| Game-side installs (`Mods/RealEarth`, GeneratedWorlds copies) | Mod DLL, config, installed world/pack copies | Yes: `make install`, install scripts | not backed up (regenerable) |
| Save games (`$USERDATA/Saves`) | Stock game saves | No, but owned by the stock game (see BackupMod notes in GAP_HARMONY_MODLETS) | test harness moves old saves to `Saves_trash` with a 7 day window instead of deleting |
| `<Managed>/Assembly-CSharp.dll` | Stock engine DLL | Always recoverable: Steam Verify regenerates it, and the mod never writes it | see [GAME_VERSION](GAME_VERSION.md) |

The terrarium cache matters most for the remote-data-loss disaster: with it,
every pack and world stays rebuildable even if the AWS dataset changes or
disappears. Without it, rebuilds depend on a third party staying alive.

## RPO / RTO per disaster

| Disaster | Without this repo's tooling | With tooling used |
|---|---|---|
| Repo disk dies | Total loss of all worlds and packs; RPO infinite | RPO = last archive copied off-host; RTO = minutes (`artifacts-restore`) |
| AWS Terrarium dataset vanishes | Packs unreproducible; every future rebuild silently degrades to synthetic fallback | No impact while `data/cache/terrarium` is present (and archived) |
| Bad bake overwrites a good world | Gone; `worlds/` has no history | Bakes never overwrite in place: the previous tree is renamed `<world>.pre-bake-<UTC stamp>` next to it (delete it once happy). Fallback: last archive or re-bake offline from pack + cache |
| Game update breaks the runtime YDim patch | `heightMode=stock`, peaks clamp ~250 | Rebuild against the new DLL (`make install`/`make build`); no backup to restore because no DLL is edited |
| Harness run pointed at real userdata deletes saves | Permanent loss | `Saves_trash/<timestamp>` window, 7 days default (`RE_SAVE_TRASH_DAYS`) |
| Install overwrites a hand-edited `GeneratedWorlds` world | Permanent loss of edits no archive holds | Previous world kept at `GeneratedWorlds_trash/<UTC stamp>__<name>` |

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
```

Restore:

```bash
make artifacts-restore ARCHIVE=backups/realearth-artifacts-20260826T120000.tar.gz
RE_FORCE_RESTORE=1 make artifacts-restore ARCHIVE=...   # move existing dirs aside first
```

The script verifies the gzip stream and sha256 before declaring success, and
refuses corrupt archives or silent overwrite on restore. A zero-byte or
truncated archive fails the command instead of passing quietly.

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
missing or tampered archive, and installing a world into `GeneratedWorlds`
moves the previous tree to `GeneratedWorlds_trash` with its contents intact.
CI runs it on every change to keep the claim current
(`scripts/artifacts_drill.sh`).

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
   Nothing prunes that directory: delete entries yourself once the new world
   is what you want.

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

- **2026-09-28:** World installs move the previous `GeneratedWorlds` tree aside instead of deleting it; `artifacts-status` reports archive age and checksum.
- **2026-08-26:** Registered as durability posture hub (state inventory, RPO/RTO, procedures, drill).
