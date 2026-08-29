# Compatibility matrix

**Owns:** which game builds / installs / hooks / modes are tested and how to
re-verify after a TFP patch. **Not:** install how-to ([MODLET](MODLET.md)),
expand policy ([HEIGHT_LIMITS](HEIGHT_LIMITS.md)), per-layer status
([MODIFICATIONS](MODIFICATIONS.md)). Hub: [INDEX](INDEX.md).

Kept honest: a row is **Live-tested** only when a real game build was booted
with the mod and the log markers are named here. Offline-only evidence is
labeled as such (per [IMPLEMENTATION_PLAN](IMPLEMENTATION_PLAN.md) status
discipline: "Do not mark live inject/MP Done without dedicated evidence").

## Game builds

| Build | Verified | Where | Notes |
|---|---|---|---|
| **V3.1.0 (b14)** Henpocalypse | Offline only | CI + docs | Previous pin; superseded by the Steam 2026-08-28 update |
| **V3.2.0 (b9)** | **Live (dedicated)** | This machine | Dedicated log: `Version: V 3.2.0 (b9)`; retargeted 2026-08-28 |

Client (Proton) boot on 3.2.0 still needs a logged-in Steam session to launch;
the verify steps are the same as [GAME_VERSION.md](GAME_VERSION.md) (boot → New
Game → `[RealEarth] RealEarth init OK` in `output_log_*.txt`). The dedicated
and client share the same `Assembly-CSharp` constants structure (the mod is
compiled against the client install's Managed dir), so hook binding is not
expected to differ; this is stated as untested until a client boot is run.

## Installs

| Install | Path | Engine expand | Mod |
|---|---|---|---|
| Client (Proton 10/11) | `…/Steam/steamapps/common/7 Days To Die` | YDim=32768 (marker verified) | `Mods/RealEarth` |
| Dedicated (native Linux) | `…/7 Days to Die Dedicated Server` | YDim=32768 (marker verified) | `Mods/RealEarth` |
| Proton userdata | `…/compatdata/251570/pfx/…/Roaming/7DaysToDie` | n/a | World install target |

Both `Assembly-CSharp.dll` files carry `.re_stock_bak` + `.re_height_expanded`
markers; `make engine-verify` checks the patched hash, `make engine-restore`
restores the stock backup.

## Harmony targets (V3.2.0 b9, live dedicated)

Bound with fail-soft reflection (missing target logs, does not kill the mod):

| Group | Targets | Live count |
|---|---|---|
| Height queries | `TerrainGeneratorWithBiomeResource.GetTerrainHeightAt`, `TerrainFromRaw.GetTerrainHeightAt`/`GetTerrainHeightByteAt`, `TerrainFromDTM.GetTerrainHeightAt`/`GetTerrainHeightByteAt`, `World.GetHeightAt`, `World.GetTerrainHeight` | 7 patched, 0 failed |
| Terrain gen | `TerrainGeneratorWithBiomeResource.GenerateTerrain` (x2), `ChunkProviderGenerateWorld.generateTerrain` (x2) | 4 |
| Chunk index | `ChunkProviderGenerateWorldFromRaw.FillOccupiedMap`, `ChunkProviderAbstract.FillOccupiedMap` | 2 |
| Player tick | `EntityPlayer.Update`, `EntityPlayerLocal.Update`, `EntityPlayer.OnEntityUnload`, `EntityAlive.OnEntityUnload` | 2 + 2 unload |
| World ready / save | `GameManager.StartGame`, `GameManager.SaveWorld`, `World.SaveWorldState` | 3 |

Startup verdict logged on 3.2.0: `injectOk=True productOk=True` with
`heightMode=ydim-expanded expanded=True`.

## Engine patcher (YDim expand)

| Aspect | Value |
|---|---|
| Tool | `tools/engine_patcher` (`EngineHeightPatcher`, Mono.Cecil) |
| Target | YDim 256→32768, YPow 8→15, Layers 64→8192, masks 255→32767, `cMaxHeight`→32767 |
| Rewrites on 3.2.0 | 9 constant-table + 76 IL Ldc per install |
| Re-run safety | `--force` restores stock from `.re_stock_bak` first |
| Steam update | Stale marker (`sha256` mismatch) auto-refreshes the backup from the current stock build before re-patching |
| Verify / restore | `make engine-verify` / `make engine-restore` |

## Operating modes

| Mode | Offline | Live |
|---|---|---|
| Baked (`MapMode=Baked`) | CI (`test-fast`, bake checks) | Partial (baked world loads; inject evidence via Streamed runs) |
| Streamed (`MapMode=Streamed`) | CI | **Live** (3.2.0 dedicated: `RealEarth init OK`, spawn sample `gameY=500`, world load + soak clean) |
| SoloSlide | `test_multiplayer.py`, `test_local_window.py` | Not live (needs client window moves) |
| SharedFixed | `test_mp_runtime_structure.py` | **Live** (3.2.0 dedicated: `mpOrigin=SharedFixed` active; multi-player distance proof open) |
| Longitude wrap | `test_host_fold.py` | Not live (needs full-planet pack) |

## Research cross-check (V3.2.0 b9)

Cross-referenced against the engine-research exact-diff changelog
([`changelog-3.2.0.md`](../../7dtd-engine-research/docs/changelog-3.2.0.md),
IL-verified 2026-08-28):

- **Unchanged (verified by IL diff, consistent with our live results):**
  world/chunk constants (dims, layers, heightmaps) — matches our expand
  rewriting the same 9 constants + 76 IL sites as on 3.1.0; save format
  (`CurrentSaveVersion` 23, `WorldState.SaveLoad` IL 926) — session snapshot
  hooks unaffected; core loop (`gmUpdate` 631 IL, 20 TPS); console command
  registry byte-identical — `re*` commands unaffected; LiteNetLib pins and
  default port 26900 unchanged.
- **Changed, no RealEarth touchpoints (grep-verified):** wire `NetPackageDamageEntity`
  (packed flags + KillXPScale, breaking), POI metadata packages
  (`NetPackagePOIAround` removed → Request/Response), `NetPackageConfirmSpawnEntity`
  + `EntityCreationData` tail, `ItemValue` flags, `EntityBuffs` kill-XP call
  sites, deco suppression (`DesignatedAreaStore` / `DynamicPrefabDecorator`).
  RealEarth's C# references none of these; the network inspector
  (`tools/network_protocol_inspector`) dumps the live DLL rather than hardcoding
  layouts, so it tracks any build automatically. LiteNetLib bot clients
  (sibling `7dtd-loadgen`) are the consumers that must track the damage/entity
  wire changes.
- **Note:** third-party mods compiled against 3.1.0 can break on 3.2.0
  (observed: `EntityBuffs.SetCustomVar` missing in an installed bot mod);
  that is a mod rebuild issue, not a RealEarth one.

## Known limits and third-party notes

- Height query **byte** returns stay lossy by design (`GetTerrainHeightByteAt`).
- Per-chunk `Height inject` lines require a connected player to generate
  chunks (dedicated with 0 players generates 0 chunks). Covered by loadgen
  scenarios in sibling [`7dtd-loadgen`](../../7dtd-loadgen/docs/REALEARTH.md).
- Third-party mods compiled against 3.1.0 can break on 3.2.0 (observed:
  `EntityBuffs.SetCustomVar` missing in an installed bot mod); this is not a
  RealEarth issue.
- `-nographics` Linux dedicated boot crash seen during the 2026-08-28 Steam
  update was a mid-update file mismatch (stock and expanded crashed
  identically; both installs boot cleanly after the update completed).

## Re-verify after a TFP patch

1. `make build` (compiles against the live Managed dir).
2. `make engine-expand` (re-applies YDim; auto-refreshes stale backup).
3. `make engine-verify`.
4. `RE_SERVER_WAIT=480 RE_SERVER_SOAK=60 bash scripts/run_dedicated_height_test.sh`
   (expect `PASS: dedicated server loaded + soaked cleanly`).
5. Client: Steam → New Game → RealEarth → check `[RealEarth] RealEarth init OK`.

## Related docs

| Doc | Role |
|---|---|
| [GAME_VERSION](GAME_VERSION.md) | Pinned build + retarget note |
| [MODLET](MODLET.md) | Install + expand |
| [MODIFICATIONS](MODIFICATIONS.md) | Per-layer status |
| [realearth-runtime](realearth-runtime.md) | Streamed runtime lessons |
| [realearth-review](realearth-review.md) | Residual risks |
