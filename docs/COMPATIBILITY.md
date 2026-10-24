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
| **V3.1.0 (b14)** Henpocalypse | Offline only | CI + docs | Previous pin; superseded |
| **V3.2.0 (b9)** | **Live (dedicated)** | This machine | Dedicated log: `Version: V 3.2.0 (b9)`; retargeted 2026-08-28. Last live soak; kept as history |
| **V3.3.0 (b18)** | **IL + assembly check only** | This machine | Current pin. Dedicated log `Version: V 3.3.0 (b18)`; hook targets re-checked against both b18 assemblies; **no mod boot on b18 yet** |

Client (Proton) boot on 3.3.0 still needs a logged-in Steam session to launch;
the verify steps are the same as [GAME_VERSION.md](GAME_VERSION.md) (boot → New
Game → `[RealEarth] RealEarth init OK` in `output_log_*.txt`). The dedicated
and client share the same `Assembly-CSharp` structure (the mod is compiled
against the client install's Managed dir); every reflection target present on
the dedicated assembly is also present on the client assembly (2026-10-24
`monodis` check), but no b18 client boot has run. This is stated as untested
until that boot happens.

## Installs

| Install | Path | Engine expand | Mod |
|---|---|---|---|
| Client (Proton 10/11) | `…/Steam/steamapps/common/7 Days To Die` | YDim=32768 (runtime hot-patch) | `Mods/RealEarth` |
| Dedicated (native Linux) | `…/7 Days to Die Dedicated Server` | YDim=32768 (runtime hot-patch) | `Mods/RealEarth` |
| Proton userdata | `…/compatdata/251570/pfx/…/Roaming/7DaysToDie` | n/a | World install target |

The YDim expand is hot-patched at boot by the runtime transpiler
(`EngineHeightRuntimePatch=true`); no DLL is edited, so there is no marker,
backup or restore step.

## Harmony targets

Target names checked against the V3.3.0 b18 dedicated assembly (IL) and both
b18 assemblies (reflection surface, `monodis`, 2026-10-24). Live counts below
are from the last live soak, on V3.2.0 b9; the b18 re-soak is open.

| Group | Targets | Last live count (b9) |
|---|---|---|
| Height queries | `TerrainGeneratorWithBiomeResource.GetTerrainHeightAt`, `TerrainFromRaw.GetTerrainHeightAt`/`GetTerrainHeightByteAt`, `TerrainFromDTM.GetTerrainHeightAt`/`GetTerrainHeightByteAt`, `World.GetHeightAt`, `World.GetTerrainHeight` | 7 patched, 0 failed |
| Terrain gen | `TerrainGeneratorWithBiomeResource.GenerateTerrain` (x2), `ChunkProviderGenerateWorld.generateTerrain` (x2) | 4 |
| Chunk index | `ChunkProviderGenerateWorldFromRaw.FillOccupiedMap`, `ChunkProviderAbstract.FillOccupiedMap` | 2 |
| Player tick | `EntityPlayer.Update`, `EntityPlayerLocal.Update`, `EntityPlayer.OnEntityUnload`, `EntityAlive.OnEntityUnload` | 2 + 2 unload |
| World ready / save | `GameManager.StartGame`, `GameManager.SaveWorld`, `World.SaveWorldState` | 3 |

All of these methods still exist in b18 with unchanged signatures.
`EntityPlayerLocal.OnEntityUnload` (66 -> 69 IL) and `GameManager.StartGame`
(21 -> 24 IL) changed body; both are postfix hooks, so binding is unaffected.
The prefab placement path (`PrefabCache.GetPrefab` IL=47,
`PrefabInstance::.ctor` IL=67, `CopyIntoWorld` IL=85) is unchanged.

Startup verdict logged on 3.2.0 (b9): `injectOk=True productOk=True` with
`heightMode=ydim-expanded expanded=True`. Not yet re-logged on b18.

## Engine height expand (runtime YDim transpiler)

| Aspect | Value |
|---|---|
| Mechanism | Harmony transpilers at boot (`EngineHeightRuntimePatch=true`) |
| Target | YDim 256→32768, YPow 8→15, Layers 64→8192, masks 255→32767 |
| Steam update | No DLL is edited; the transpiler binds against the new build at boot |
| Re-apply | `make install` after a TFP patch |

## Operating modes

The Live column is the last live evidence, recorded on V3.2.0 (b9). No mode
has been re-run on V3.3.0 b18 yet.

| Mode | Offline | Live |
|---|---|---|
| Baked (`MapMode=Baked`) | CI (full `make test` suite, bake checks) | Partial (baked world loads; inject evidence via Streamed runs) |
| Streamed (`MapMode=Streamed`) | CI | **Live** (3.2.0 dedicated: `RealEarth init OK`, spawn sample `gameY=500`, world load + soak clean) |
| Streamed below-sea (trench) | `test_build_trench_pack_uses_product_sea_anchor` | **Live** (2026-08-29: trench pack at sea 16000, spawn sample `gameY=5000` = -11000 m floor, clean soak) |
| SharedFixed multi-bot | `test_mp_runtime_structure.py` | **Live** (2026-08-29: H500, 6 bots concurrent, SharedFixed active, 4 players, prefab stamps on real surface Y; stock join-churn race needs a gentle ramp or the EfficientServer snapshot patch) |
| SoloSlide | `test_multiplayer.py`, `test_local_window.py` | Not live (needs client window moves) |
| SharedFixed | `test_mp_runtime_structure.py` | **Live** (3.2.0 dedicated: `mpOrigin=SharedFixed` active; multi-player distance proof open) |
| Longitude wrap | `test_host_fold.py` | Not live (needs full-planet pack) |

## Research cross-check (V3.3.0 b18)

Cross-referenced against the engine-research exact-diff changelog
([`changelog-3.3.0.md`](../../7dtd-engine-research/docs/releases/changelog-3.3.0.md),
IL-verified 2026-10-24). Save records and inventory owners:
[`save-region.md`](../../7dtd-engine-research/docs/world/save-region.md),
[`items.md`](../../7dtd-engine-research/docs/gameplay/items.md).

- **Unchanged (verified by IL diff):** world/chunk constants (dims, layers,
  heightmaps), which matches our expand rewriting the same 9 constants and IL
  sites; `WorldState.CurrentSaveVersion` 23, `WorldState.SaveLoad` IL 926 and
  the whole `main.ttw` / `.7rg` container; the chunk preamble 47; `gmUpdate`
  631 -> 638 IL with the 20 TPS budget unchanged; the height, generate and
  chunk-index hook targets above.
- **Changed, save-side (affects shipped worlds, not our parser):**
  `EntityCreationData` 37 -> 38, `TEFeatureStorage` 18 -> 20, `Bag` 1 -> 2,
  `Equipment` 4 -> 6, `Quest.FileVersion` 8 -> 9, `.ttp` 59 -> 62. b18 reads a
  b10 save (live check: a b10 `main.ttw` booted on b18 with only the
  different-version warning); b10 cannot read a b18 save. RealEarth writes no
  entity/tile-entity/`.ttp` record, so the only downgrade guard needed is the
  `main.ttw` version stamp, which refuses an older label
  (`tools/realearth/generated_world.py`).
- **Changed, no RealEarth touchpoints:** inventory/equipment rework (`Hand`,
  `ItemStackGrid`), `NetPackagePlayerInventory` blobs, six
  `NetPackageInventory*`/`Transaction*` types removed, signs subsystem,
  `AssetManagement` handle layer, `Services.Analytics` send sites, console
  registry 188 -> 190 (`give`, `listitems`), prefab cell storage in
  `Prefab.CellPool`. RealEarth's C# references none of the removed members; the
  prefab path uses only prefab-level APIs, which are unchanged.
- **Note:** third-party mods compiled against 3.2.0 can break on 3.3.0; that is
  a mod rebuild issue, not a RealEarth one.

## Known limits and third-party notes

- Height query **byte** returns stay lossy by design (`GetTerrainHeightByteAt`).
- Per-chunk `Height inject` lines require a connected player to generate
  chunks (dedicated with 0 players generates 0 chunks). Covered by loadgen
  scenarios in sibling [`7dtd-loadgen`](../../7dtd-loadgen/docs/REALEARTH.md).
- Third-party mods compiled against an older build can break on 3.3.0 (observed
  on 3.2.0: `EntityBuffs.SetCustomVar` missing in an installed bot mod); this
  is not a RealEarth issue.
- `-nographics` Linux dedicated boot crash seen during the 2026-08-28 Steam
  update was a mid-update file mismatch (stock and expanded crashed
  identically; both installs boot cleanly after the update completed).

## Re-verify after a TFP patch

1. `make build` (compiles against the live Managed dir).
2. `make install` (re-applies the mod; the runtime transpiler binds at boot).
3. `RE_SERVER_WAIT=480 RE_SERVER_SOAK=60 bash scripts/run_dedicated_height_test.sh`
   (expect `PASS: dedicated server loaded + soaked cleanly`).
4. Client: Steam → New Game → RealEarth → check `[RealEarth] RealEarth init OK`.

## Related docs

| Doc | Role |
|---|---|
| [GAME_VERSION](GAME_VERSION.md) | Pinned build + retarget note |
| [MODLET](MODLET.md) | Install + expand |
| [MODIFICATIONS](MODIFICATIONS.md) | Per-layer status |
| [realearth-runtime](realearth-runtime.md) | Streamed runtime lessons |
| [realearth-review](realearth-review.md) | Residual risks |
