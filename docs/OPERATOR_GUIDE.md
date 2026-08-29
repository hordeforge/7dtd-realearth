# RealEarth first-time operator guide

**Owns:** the end-to-end walkthrough for a new operator: install, expand,
verification, troubleshooting, rollback, and save compatibility.
**Not:** config key reference ([MODLET.md](MODLET.md)), artifact backup
posture ([BACKUP_RESTORE.md](BACKUP_RESTORE.md)), Proton paths
([PROTON_INSTALL.md](PROTON_INSTALL.md)), per-layer status
([MODIFICATIONS.md](MODIFICATIONS.md)). Hub: [INDEX.md](INDEX.md).

Read this top to bottom once, then keep it as the troubleshooting checklist.
Assumes a stock 7 Days to Die V3.2.0 (b9) install and the sibling
`7dtd-loadgen` project only if you want bot soak evidence.

---

## 1. What you are installing

| Piece | Role |
|---|---|
| `RealEarth.dll` + `ModInfo.xml` | Config, tiles, streamer, session |
| `Config/realearth.json` | Product defaults: Streamed, 1:1 height, SoloSlide/SharedFixed |
| `Data/tiles/` | `.rte` elevation packs (demo pack shipped) |
| `Tools/` (`EngineHeightPatcher.exe` + `apply_engine_expand.sh`) | YDim expand (part of this mod) |

Product height model: `gameY = SeaLevelGameY(16000) + elev_m` (1 m ≈ 1 block).
Expand raises the engine column to YDim=32768 so real relief fits both ways:
~12 km up (airliner band, ceiling 29000) and real depth below sea (trench
-11 km → gameY 5000). See [HEIGHT_LIMITS.md](HEIGHT_LIMITS.md).

## 2. Before you start

1. **Close 7DTD and any dedicated server** (Steam Verify or a running server
   will be overwritten).
2. Confirm the game path (`make setup` checks it):
   `SEVENDTD_GAME_DIR="$HOME/.local/share/Steam/steamapps/common/7 Days To Die"`
3. Confirm `Mods/0_TFP_Harmony` exists (required; do not delete).
4. Disk: the expanded DLL is ~11 MB; the demo pack ~10 MB; nothing huge.

## 3. Install (product path)

```bash
make install-full        # YDim expand (client + dedicated) + mod install
```

Step by step, the same thing:

```bash
make engine-expand       # client + dedicated Assembly-CSharp, YDim=32768
make install             # mod + worlds into the game Mods/GeneratedWorlds
```

The expand writes `.re_stock_bak` (stock DLL) and `.re_height_expanded`
(marker) next to each `Assembly-CSharp.dll`; both installs get patched. If a
Steam update already replaced the DLL, the patcher detects the stale marker
and refreshes the stock backup from the current build before re-patching, so a
plain re-run converges (no manual restore dance).

For the height-test packs instead of the demo pack:

```bash
make install-height-500        # staged 500-block peak (fast test)
make install-height            # Everest DEM pack
make height-map-trench         # staged below-sea trench pack (real depth test)
```

## 4. Verify

### 4.1 Engine expand

```bash
make engine-verify       # compares the DLL bytes against the expand-time sha256
```

`realearth engine-audit` (via `cd tools && uv run --locked python -m realearth.cli engine-audit`)
prints the live constants: `ChunkBlockYDim` should read **32768**.

### 4.2 In-game

1. Launch 7DTD (Steam/Proton).
2. New Game → `RealEarth` (or `RealEarth_H500` / `RealEarth_HeightTest`).
3. The log (`output_log_*.txt` under the game or Proton logs) must contain:

```
[RealEarth] RealEarth init OK. mode=Streamed heightMode=ydim-expanded ...
[RealEarth] EngineHeightMod: RealEarth YDim expand active YDim=32768 ...
```

`heightMode=ydim-expanded` is the product state. If it says `engineHeight=...`
with a 250-clamp, the expand did not take effect (see §6).

### 4.3 Headless dedicated (soak)

```bash
RE_SCENARIO_PACK=h500 RE_WORLD_NAME=RealEarth_H500 RE_SERVER_WAIT=480 \
  RE_SERVER_SOAK=60 bash scripts/run_dedicated_height_test.sh
# expect: PASS: dedicated server loaded + soaked cleanly (SharedFixed MP path).
# trench variant: RE_SCENARIO_PACK=trench RE_WORLD_NAME=RealEarth_T11000 ...
```

The log should show per-chunk `Height inject chunk=(...) maxH=... sessionPeak=...`
lines and `Session snapshot` write on save. Bot soak evidence lives in the
sibling `7dtd-loadgen` (`make scenarios`, `re-h500-join-wander` etc.).

## 5. Backup

```bash
make artifacts-backup   # checksum-verified archive of worlds, packs, tile cache, viewer data
make artifacts-restore ARCHIVE=path/to/realearth-artifacts-*.tar.gz
```

See [BACKUP_RESTORE.md](BACKUP_RESTORE.md) for the full RPO/RTO posture.
The expand backups live next to the DLLs (`.re_stock_bak`); `make artifacts-backup`
does not cover those, because Steam Verify or a re-expand regenerates them.

## 6. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `RealEarth init OK` but `heightMode=stock` / peaks clamp ~250 | Expand missing or undone (Steam Verify) | `make engine-expand`, restart |
| `HEIGHT CAPPED to allocY=...` in log | Config ceiling above engine YDim | Re-expand, or lower `EngineMaxGameY` |
| World shows ocean everywhere | `.rte` tiles missing / pack not copied | Re-run `make install`; check `Mods/RealEarth/Data/tiles/earth.manifest.json` exists |
| `MISSING TARGET: <patch>` in log | A Harmony target renamed by a game update | Rebuild against the new DLL (`make build`), confirm game version in [GAME_VERSION.md](GAME_VERSION.md) |
| Game crashes at boot right after a Steam update | Mid-update file mismatch | Let the update finish, then `make engine-expand` + `make install` |
| Globe view fails | (Viewer) missing `viewer/vendor/three/` | `bash scripts/vendor-three.sh` |
| Pack won't load in viewer | Broken `viewer.json` (no layers, degenerate bbox) | Re-export the pack; error names the bad field |
| Dedicated server segfaults at entrypoint | Pre-existing on some Linux builds / mid-update state | Confirm stock also crashes (not mod-related); see [COMPATIBILITY.md](COMPATIBILITY.md) |

## 7. Rollback

```bash
make engine-restore     # restores stock Assembly-CSharp from .re_stock_bak (client + dedicated)
```

Then remove `Mods/RealEarth` from both installs to uninstall the mod. Worlds
generated by the mod are regular 7DTD saves and remain loadable on a stock
engine only in the Baked band (~250); Streamed/1:1 saves reference absolute
heights that stock cannot represent (see §8).

## 8. Save compatibility

- **Game save format is stock:** `CurrentSaveVersion` 23 is unchanged by
  RealEarth (verified against the V3.2.0 IL diff); the mod does not alter the
  `.7rg`/region save format.
- **Session snapshot:** `Mods/RealEarth/Config/realearth.session.json` records
  the absolute Earth origin (`absoluteX/absoluteZ`, scope). It is written on
  save and restored on load; deleting it resets the origin to the spawn bbox.
- **Height caveat:** a save made on an expanded engine has tall columns (up to
  29000). Opening it on a stock engine clamps vertical data to ~250 — that is
  data loss for 1:1 content, so keep the engine expanded for the same world.
- **Per-mod config:** `Config/realearth.json` is regenerated by `make install`;
  edits are preserved only if you re-apply them (or use `mod_config`).

## 9. Related docs

| Doc | Role |
|---|---|
| [MODLET.md](MODLET.md) | Config keys, env vars, step-by-step install |
| [HEIGHT_LIMITS.md](HEIGHT_LIMITS.md) | Vertical budget, sea anchor, depth |
| [BACKUP_RESTORE.md](BACKUP_RESTORE.md) | Artifact backup/restore, RPO/RTO |
| [PROTON_INSTALL.md](PROTON_INSTALL.md) | Proton paths on this machine |
| [COMPATIBILITY.md](COMPATIBILITY.md) | Build/hook/mode matrix |
| [GAME_VERSION.md](GAME_VERSION.md) | Pinned game build + retarget notes |
| [MODIFICATIONS.md](MODIFICATIONS.md) | Per-layer Done/Partial status |

## Changelog

- **2026-08-29:** Initial guide (install-full, verify markers, trench soak
  variant, rollback, save-compat caveats).
