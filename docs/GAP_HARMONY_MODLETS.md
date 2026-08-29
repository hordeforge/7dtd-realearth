# Gaps and 7D modding APIs

**Owns:** what is still missing to implement, and **which 7D API** (XPath, IModApi, Harmony, XUi, WebMod, binary expand, bake, pipeline).  
**Not:** compact status dashboard ([MODIFICATIONS](MODIFICATIONS.md)); stock limit map ([ENGINE_LIMITATIONS](ENGINE_LIMITATIONS.md)). Hub: [INDEX](INDEX.md).

Prefer the **shallowest** API (workspace [MODDING_BEST_PRACTICES](../../MODDING_BEST_PRACTICES.md)). V3.1.0 adds no new mod API surface vs V3.0. Harmony targets: rediscover after each TFP patch ([terrain-height](../../7dtd-engine-research/docs/terrain-height.md)).

**Rule of thumb:** XML for data tables · IModApi for session/commands · Harmony for height/gen/tick · binary expand for YDim · packs for DEM. Never a second Harmony; never private per-client origins.

---

## 0. RealEarth vs other 7D modding APIs

### 0.1 Official / stock API inventory

| API surface | Who provides it | How you use it | Survives Steam update? | EAC / crossplay |
|---|---|---|---|---|
| **Mods folder + `ModInfo.xml`** | TFP loader | Every in-game mod | Folder survives; content may break | Content mods usually EAC off |
| **XML / XPath modlet** | TFP config merge | `Mods/*/Config/**` with `<configs>` XPath ops | If XPath still matches | Often OK for pure XML |
| **`Localization.csv`** | TFP | Mod root CSV (not `.txt`) | New keys OK | Same as XML |
| **XUi (V3)** | TFP | `Config/XUi_InGame`, `XUi_Menu`, `XUi_Common` + `{% %}` | Fragile on UI rework | Client install |
| **Asset bundles / UIAtlases** | Unity + TFP | Icons, models, sounds | Must match Unity **2022.3.62f2** | Every client |
| **`IModApi` (ModAPI)** | TFP | `InitMod(Mod)`; load DLL | Rebuild each update | EAC off |
| **`ConsoleCmdAbstract`** | TFP | Subclass; auto-discovered | Rebuild | EAC off |
| **Stock `0_TFP_Harmony`** | TFP (HarmonyX stack) | Reference `0Harmony`; do **not** ship a second | Patch sites break on renames | EAC off (`SkipWithAntiCheat`) |
| **Harmony Prefix/Postfix/Transpiler** | Harmony via stock | Intercept `Assembly-CSharp` methods | Breaks on IL/name change | EAC off |
| **WebDashboard + WebMod** | TFP core (V3) | `WebMod/` plugin + dashboard port | Rebuild plugin | Server admin; not crossplay console |
| **SandboxCode / serverconfig** | TFP | Difficulty, slots, world knobs | Key renames across majors | Server ops |
| **Telnet / console API** | TFP dedicated | External tools, CSMM-style | Stable enough for ops | No client mod |
| **GeneratedWorld / prefab files** | TFP world load | Bake path for finite maps | Format can change | Content |
| **RWG / heightmap import path** | TFP + community importers | PNG DTM ≤255 height | Tool version pin | Not Streamed planet |
| **Binary IL patch (Cecil)** | Not a TFP API | RealEarth expand tools | **Verify undoes** | Never EAC |

**Not supported / dead for V3 product work**

| Legacy | Status | RealEarth stance |
|---|---|---|
| **SDX** (old script/injection stack) | Obsolete for modern TFP | Do not use |
| Pre-3.0 **`XUi/` + `{binding}`** | Superseded by `XUi_InGame` + `{% %}` | Do not write new UI that way |
| **`Localization.txt`** | → `Localization.csv` | Do not ship .txt |
| Separate **WebDashboard.dll** refs | WebDashboard is **core** in V3 | Reference game assembly only |
| Editing vanilla `Data/Config` on disk | Wiped by updates | Always XPath |

### 0.2 Capability matrix (API × RealEarth needs)

| RealEarth need | XPath XML | IModApi only | Harmony | XUi | WebMod | World bake | Offline pipe | Binary expand | Telnet/ops |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Balance loot/HP/recipes | **Yes** | no | overkill | no | no | no | no | no | no |
| City map name class | **Yes** (`nav_objects`) | no | optional | no | no | no | data | no | no |
| Spawn/gamestage by density | **Yes** | soft scale | optional | no | no | stamps | density | no | no |
| Console debug (`reheight`) | no | **Yes** | no | no | no | no | no | no | yes |
| JSON config / session object | no | **Yes** | no | no | no | no | no | no | no |
| Override terrain height | no | alone **no** | **Yes** | no | no | bake only | DEM | helps tall | no |
| Rewrite GenerateTerrain | no | no | **Yes** | no | no | bake only | DEM | no | no |
| Origin slide / stream tick | no | session **Yes** | **tick hooks** | no | no | no | no | no | no |
| Raise YDim past 255 | no | no | no | no | no | no | no | **Yes** | no |
| Globe / lon-lat HUD | strings | bindings | optional | **Yes** | no | no | no | no | no |
| Admin “which pack loaded” | no | console | no | no | **Yes** | no | no | no | **Yes** |
| Full-planet Streamed DEM | no | streamer | **inject** | no | no | **no** | **tiles** | tall Y | no |
| Fake 1000 clients | no | no | no | no | no | no | no | no | loadgen (external) |
| AI/mesh FPS budgets | soft | no | EfficientServer | no | no | no | no | no | measure APM |

**Takeaway:** RealEarth is **not** an XML-only mod. Product path is **IModApi + Harmony + (binary expand) + offline packs**. XML/XUi are support layers for names, difficulty, and globe UI.

### 0.3 API-by-API: fit for RealEarth

#### XPath XML modlets

| | |
|---|---|
| **What** | TFP merges `Mods/*/Config` into vanilla `Data/Config` via XPath |
| **Strengths** | Shallowest; no C# rebuild for balance; server can push XML in some setups |
| **Weaknesses** | Zero DEM authority; no coords; no tall columns; breaks when XML shape renames (V3 pipe/MapColor churn) |
| **RealEarth now** | `nav_objects.xml` real; biomes/rwgmixer stubs |
| **RealEarth later** | biomes, spawning, gamestages, weather, Localization, XUi patches |
| **Vs others** | SphereII/overhauls live here heavily; heightmap importers barely need it |

#### IModApi (official C# entry)

| | |
|---|---|
| **What** | `IModApi.InitMod` when DLL loads; access `Mod` path, log, register systems |
| **Strengths** | Official lifecycle; console cmds; load config; start streamer/session **without** patching |
| **Weaknesses** | Does not intercept stock height/gen by itself; needs Harmony for that |
| **RealEarth now** | `ModApi` loads config, tiles, Harmony bootstrap, session |
| **Pattern** | Session + streamer + catalogs in IModApi; inject in Harmony |
| **Vs others** | ServerTools / IceCoffee / Allocs plugins also enter here; admin tools stop at ModAPI+events when possible |

#### ConsoleCmdAbstract

| | |
|---|---|
| **What** | F1 / dedicated console commands auto-discovered from mod assemblies |
| **Strengths** | Fast debug; no UI; works dedicated |
| **Weaknesses** | Not player UX; not a data plane |
| **RealEarth now** | `reheight`, `rereveal`, `recities`, `reinject`, `resession` |
| **Later** | `relonlat`, tile cache stats |
| **Vs others** | TFP_CommandExtensions stock sample; ServerTools dozens of cmds |

#### Harmony (via stock 0_TFP_Harmony)

| | |
|---|---|
| **What** | Prefix/Postfix/Transpiler on managed methods; stock ships HarmonyX + MonoMod + Cecil |
| **Strengths** | Only practical way to own height/gen/tick inside compiled game |
| **Weaknesses** | Breaks every rename; EAC off; never ship second Harmony |
| **RealEarth now** | Reflection discovery patches (height, gen, player, world ready) |
| **Style note** | RealEarth prefers **runtime discovery** over hard-typed targets (survive more renames, harder to audit). EfficientServer uses explicit patch groups. Both valid; document which targets hit. |
| **Vs others** | SphereII: many gameplay patches; OCB: systems (electricity); EfficientServer: AI/mesh budgets only; heightmap importers: RWG height hooks for bake |

#### XUi (V3 UI API)

| | |
|---|---|
| **What** | Declarative HUD/menu under `XUi_*` + NCalc `{% %}`; custom bindings from IModApi |
| **Strengths** | Official UI; no IMGUI fight for stock-looking HUD |
| **Weaknesses** | V3 overhaul still churning; full HUD rewrite pending upstream |
| **RealEarth now** | Minimal / stub menu XML |
| **Later** | Globe panel, lon/lat readout, discovered cities list |
| **Vs others** | HUDPlus-class mods; do not put terrain logic in XUi |

#### WebDashboard / WebMod

| | |
|---|---|
| **What** | Core web admin (V3); plugins add panels/routes |
| **Strengths** | Ops visibility without in-world UI |
| **Weaknesses** | Not geography; not client map |
| **RealEarth** | Optional later: pack name, expand YDim, streamer stats (like APM bridge pattern) |
| **Vs others** | IceCoffee/ServerKit, Allocs web map, APM bridge; **not** a substitute for inject |

#### SandboxCode / serverconfig

| | |
|---|---|
| **What** | Server difficulty and session knobs (many moved into SandboxCode in V3) |
| **Strengths** | No mod DLL for basic host settings |
| **Weaknesses** | No Earth data |
| **RealEarth** | Document recommended Sandbox/view distance for dense packs; do not encode geography here |

#### Telnet / external admin (layer 0)

| | |
|---|---|
| **What** | Out-of-process console, CSMM, bots |
| **Strengths** | Crossplay-friendly admin; empty Mods/ |
| **Weaknesses** | Cannot inject DEM |
| **RealEarth** | Ops only; loadgen is external LiteNet, not a mod API |

#### GeneratedWorld + heightmap importer path

| | |
|---|---|
| **What** | Finite world files (dtm, biomes, prefabs); community **Custom Height Map Importer** feeds RWG |
| **Strengths** | Playable **Baked** regions without Streamed inject |
| **Weaknesses** | Stock height **≤255**; size ~8-16k; not planet continuous |
| **RealEarth** | Bake path **yes** (Phase 0/Baked); importer is optional companion, **not** product Streamed path; still needs **our expand** for real Everest height |

#### Prefab / POI content API

| | |
|---|---|
| **What** | `prefabs.xml` + Prefabs folder; decoration system |
| **Strengths** | Density stamps look like 7DTD cities |
| **Weaknesses** | Kits ≠ real buildings; Y must match surface |
| **RealEarth** | Offline stamp plan + runtime Y snap (Harmony) |

#### Binary IL patch (not a TFP API)

| | |
|---|---|
| **What** | Mono.Cecil rewrite of YDim/layers (RealEarth Tools) |
| **Strengths** | Only way past compile-time 256 column |
| **Weaknesses** | Ops burden; Verify restores stock; client+dedicated parity |
| **Vs others** | Almost no public mods do this; RealEarth owns it; **must not** live in EfficientServer |

### 0.4 How other projects use the APIs

| Project class | Primary APIs | Overlap with RealEarth? |
|---|---|---|
| **Custom Height Map Importer** | Harmony/RWG + world PNGs | Baked only; 255 height; complementary, not Streamed |
| **SphereII packs** | XPath + heavy Harmony gameplay | Learn XPath/XUi; do **not** merge inject stacks |
| **ServerTools / IceCoffee ServerKit** | IModApi + Harmony admin + Web | Ops patterns (main-thread marshal); not terrain |
| **Allocs server fixes / web map** | Commands + web map of stock world | Admin map ≠ Earth lon/lat atlas |
| **OCB Electricity / StopFuel** | Harmony systems | Pattern: small focused Harmony; different domain |
| **EfficientServer (this workspace)** | Harmony AI/mesh/dedicated skips | **Sibling:** measure with APM, do not put Earth inject here |
| **7dtd-server-apm bridge** | Harmony timing + WebMod | Measure only |
| **7dtd-loadgen** | External LiteNet (not Mods/) | Soak RealEarth servers |
| **MVirus** | Mod transfer to clients | Optional distribution; not geography |
| **BackupMod** | Save zip I/O | Ops companion for tall-world saves |

### 0.5 Which API to pick for each remaining gap

| Gap cluster | First choice API | Second | Never |
|---|---|---|---|
| Height / GenerateTerrain inject | **Harmony** | binary expand for tall | XPath, WebMod |
| Session origin / streamer | **IModApi** + tick **Harmony** | | XML alone |
| City labels | XPath `nav_objects` + **IModApi** discover | NavObject reflection | WebMod |
| Metro difficulty | **XPath** gamestages/spawning | light Harmony scale | binary |
| Globe / lon-lat HUD | **XUi** + IModApi bindings | | Telnet |
| Pack / expand status for admins | ConsoleCmd + optional **WebMod** | Telnet | Harmony spam |
| Everest columns | **Binary expand** + Harmony inject | | heightmap importer alone |
| Host FPS under density | **EfficientServer** after APM | density caps in RealEarth | more POIs without budget |
| Crossplay console hosts | **No** RealEarth C# | Telnet ops only | Harmony on EAC |

### 0.6 RealEarth API stack (target)

```text
                    ┌──────────────────────────────────────┐
                    │ E Offline pipeline (.rte, settlements)│
                    └──────────────────┬───────────────────┘
                                       │ packs
     ┌─────────────────────────────────▼─────────────────────────────────┐
     │ D World bake (optional Baked)     OR    Streamed tile cache       │
     └─────────────────────────────────┬─────────────────────────────────┘
                                       │
     ┌─────────────────────────────────▼─────────────────────────────────┐
     │ IModApi: config, session, streamer, catalogs, console cmds        │
     └─────────────┬───────────────────────────────┬─────────────────────┘
                   │                               │
         ┌─────────▼─────────┐           ┌─────────▼─────────┐
         │ Harmony inject    │           │ XPath + XUi       │
         │ height/gen/tick   │           │ names, difficulty │
         │ save/POI Y later  │           │ globe HUD later   │
         └─────────┬─────────┘           └───────────────────┘
                   │
         ┌─────────▼─────────┐
         │ Binary YDim expand│  (install time; not runtime API)
         └───────────────────┘

  Sibling (not RealEarth APIs): APM measure · loadgen soak · EfficientServer budgets
  Ops only: Telnet · WebDashboard · SandboxCode
```

### 0.7 Anti-patterns

| Anti-pattern | Why it fails |
|---|---|
| “XML-only RealEarth” | Cannot inject DEM or raise YDim |
| “IModApi without Harmony for Streamed” | Stock gen still owns terrain |
| “Second Harmony in RealEarth folder” | Conflicts with `0_TFP_Harmony` |
| “WebMod as the world map” | Admin tool, not player atlas / inject |
| “Heightmap importer instead of expand” | Still 255; not 1:1 Everest |
| “EfficientServer patches for Earth height” | Wrong project; retarget cost; scope mix |
| “SDX / pre-3.0 XUi” | Dead surface on 3.0.1 |
| “Per-client private origin via Harmony” | Breaks MP combat (design blocker) |

---

## 1. What ships today (pointer)

**Status board:** [MODIFICATIONS](MODIFICATIONS.md) (do not duplicate Done/Partial tables here).

**Harmony currently (live, 3.2.0 b9):** player tick (2), world ready (1), height queries (7, failed=0), GenerateTerrain postfix (4), chunk index (2). Per-chunk `Height inject` verified live to `maxH=8778 sessionPeak=8778` (Everest) and below-sea `gameY=5000` (trench). Remaining Partial: biome paint at runtime, prefab/sleeper Y, origin slide wrap, player-delta save.  
**XML:** useful `nav_objects`; biomes/rwgmixer stubs.  
**Systems:** session, streamer, city labels, FOW debug, inject scaffold. City discovery: session-only (save/MP later).

---

## 2. Master gap matrix (what else is missing)

Legend for **Primary layer**: A binary · B Harmony · C XML · D world data · E pipeline · F ops/measure · Sys = pure C# session (no new TFP hook)

| # | Gap | Why product needs it | Primary | Secondary | Severity | Status |
|---:|---|---|---|---|---|---|
| 1 | **Complete height inject on live build** | Streamed DEM is the product | B | A, F | **Blocker** | **Done** (3.2.0 b9: heightQ=7 gen=4, per-chunk inject to `sessionPeak=8778`; Everest + trench soaks) |
| 2 | **All concrete height APIs + RWG generators** | Missed path = stock hills | B | RE dump | **Blocker** | **Done** (7 concrete APIs, failed=0) |
| 3 | **GenerateTerrain order vs mesh/decoration** | Inject overwritten or ignored | B | F | **Blocker** | **Partial** (gen postfix live; decoration/paint after inject still open) |
| 4 | **Byte heightmap lossiness** | Everest not in byte API | B + A | policy | **Blocker** | **Done** (int inject bypasses; byte APIs stay lossy by design) |
| 5 | **Y expand client+dedicated soak** | Tall mesh/physics/saves | A | F | **Blocker** | **Done** (YDim=32768 live soak; backup refresh after updates) |
| 6 | **`.7rg` / region tall-Y save-reload** | Bases at altitude | A + B | F | **Hard** | **Partial** (session snapshot save/reload live; region tall-Y open) |
| 7 | **Origin slide live proof** | Travel beyond host | Sys + B | F | **Hard** | **Partial** (SoloSlide config live; window/wrap moves open) |
| 8 | **Save absolute session** (origin, AbsoluteXZ, wrap) | Rejoin correct Earth place | B + Sys | D | **Hard** | **Done** (snapshot written + restored on restart, `Session restored absolute=(255,280)`) |
| 9 | **Player build deltas per Earth tile** | Edits survive unload | B + Sys | D | **Hard** |
| 10 | **Missing/corrupt tile fail-closed** | No silent fake DEM | Sys | E | **Hard** | **Done** (live `failClosed=True`; missing tile = ocean floor) |
| 11 | **CDN / tile fetch** | Planet scale data | Sys + E | F | **Hard** |
| 12 | **SharedFixed MP + co-located proof** | Shooting/claims | Sys | F (loadgen) | **Hard** | **Partial** (SharedFixed active live; 4-6 bots joined; multi-bot distance proof open) |
| 13 | **Net package Y/XZ range validation** | Tall/wide desync | B + F | A | **Hard** |
| 14 | **Landcover → biome at runtime** | Recognizable Earth biomes | B | C, E | **Hard** | **Partial** (SetBiomeId written from landcover; decor/sleeper open) |
| 15 | **Density stamp POIs on real surface Y** | Cities not floating/buried | B + D | E | **Hard** | **Partial** (StampSurfaceY offline; live stamp proof open) |
| 16 | **Sleeper / decoration Y after inject** | POI interiors work | B | C | **Hard** |
| 17 | **Pathfinding / A\* on cliffs** | Zombies on real DEM | B (budget) | F optim | **Hard** |
| 18 | **Water / coast fill** | Oceans and lakes | B + E | C | **Hard** |
| 19 | **Sunlight / light loops above 255** | Dark tall columns | A + B | RE | **Hard** |
| 20 | **Stability / collapse on tall fills** | Physics after inject | B | F | **Hard** |
| 21 | **Prefab/sleeper budgets by density** | Tokyo does not melt sim | C + B | F | **Hard** |
| 22 | **Spawn/gamestage by biome+density** | Difficulty geography | C | B | **Medium** |
| 23 | **Trader / quest geography** | Traders in real cities | D + C | B | **Medium** |
| 24 | **Weather / temp by latitude+landcover** | Climate feel | C + B | E | **Medium** |
| 25 | **Radiation / barren mapping** | Wasteland bands | C + E | | **Soft** |
| 26 | **Roads (OSM corridors)** | Highways | E + D | B stamp | **Later** |
| 27 | **Rivers / hydrology** | Recognizable waterways | E + B | | **Later** |
| 28 | **Lat-correct horizontal meters** | True km / city edges | Sys | E | **Medium** |
| 29 | **Antimeridian packs** | Pacific | E + Sys | | **Medium** |
| 30 | **Globe / atlas XUi** | Planet context | C (XUi) + B | Sys | **Medium** |
| 31 | **Map lon/lat HUD + grid** | Orientation | B + C | | **Soft** |
| 32 | **City discovery save/MP sync** | Sticky names across join | Sys + B | | **Medium** |
| 33 | **Production FOW** (not debug full map) | Explore real places | B | config | **Soft** |
| 34 | **Sparse Y sections** | RAM at planet+tall | A deep | B | **Later** |
| 35 | **Fall damage / kill plane / spawn Y retune** | Peaks playable | C + B | | **Soft** |
| 36 | **Vehicle / physics at extreme Y** | Edge cases | F playtest | B if broken | **Soft** |
| 37 | **Compatibility matrix / refuse bad DLL** | Silent break after update | B + F | A | **Ops** |
| 38 | **Reproducible pack manifests** | Auditable 1:1 claim | E | | **Ops** |
| 39 | **Planet tile farm** | Full coverage | E + F | | **Ops** |
| 40 | **EAC-off / install docs** | Modded servers | Docs | | **Ops** |

---

## 3. Harmony surface map (what to add)

Targets are **names from V3.1.0 research dumps**; always rediscover after TFP patches. Prefer **postfix** (safe) then **prefix skip** only when stock must not run.

### 3.1 Terrain authority (P0-P1): expand RealEarth.RuntimeHooks

| Hook class (candidates) | Method families | Purpose | Priority |
|---|---|---|---|
| `World` | `GetTerrainHeight`, `GetHeightAt` | Float/int path for tall DEM | P0 |
| `Chunk` | `GetTerrainHeight` / `SetTerrainHeight` | Chunk heightmap consistency | P0 |
| `TerrainFromDTM` / `TerrainFromRaw` | `GetTerrainHeight*`, fill | Baked + raw providers | P0 |
| `TerrainGeneratorWithBiomeResource` | `GetTerrainHeightAt`, `GenerateTerrain` | Live RWG/stream gen | P0 |
| `ChunkProviderGenerateWorld*` | `generateTerrain`, related | Provider entry | P0 |
| `MeshGeneratorMC2` / mesh gen | `GetTerrainHeight` (int) | Meshing uses int path | P1 |
| `WorldBuilder` | `GenerateTerrain*` | Map-tool / RWG builder paths if used | P2 |
| Decoration / `ChunkProvider*` FillOccupiedMap | after surface | Occupancy for POIs | P1 |

**Also needed after inject**

| Area | Candidate hooks | Why |
|---|---|---|
| Biome ID per column | biome map setters, `GetBiomeId`, paint paths | Landcover → vanilla biome id |
| Density / submersion | `SetDensity`, water density | Solid ground + coast |
| Light | sun height / light propagation loops | Tall columns black if still 0-255 only |
| Stability | support calculation after mass fill | Prevent collapse storms |

### 3.2 Session / travel (P1-P2)

| Area | Candidate hooks | Why |
|---|---|---|
| Player tick | already partial | Stream, slide, discover, FOW |
| World load / save | `GameManager` world create, save/load, `WorldState` | Persist OriginEarth, AbsoluteXZ, discoveries |
| Chunk load/unload | chunk added/removed, region IO | Delta overlay apply/save |
| Entity teleport after slide | player set position (already partial) | Keep player centered |
| Land claim / bedroll / keystones | claim manager APIs | Remap or forbid claims that break on slide |
| Vehicles | vehicle entity pos | Same as player after slide |

### 3.3 Content placement (P2-P3)

| Area | Candidate hooks | Why |
|---|---|---|
| Prefab instance Y | prefab paste / dynamic prefab | Snap to `SampleGameHeightInt` |
| Sleeper volumes | sleeper init / trigger | Volume Y on real surface |
| Trader spawn | trader POI / entity spawn | Optional density-band placement |
| Dynamic mesh | `DynamicMeshManager` | Tall + dense urban cost (measure first; optim project may own) |

### 3.4 Simulation budgets (P3+, measure first)

| Area | Candidate hooks | Owner note |
|---|---|---|
| Spawner / gamestage | spawn density, `AIDirector*` | Prefer XML gamestages; Harmony only for density scale |
| Pathfinding | ASP / `AstarPath` admission | Prefer budgets; deep A\* rewrite = optimizer |
| Entity count | despawn / interest | Sibling EfficientServer / optim, not RealEarth core |

### 3.5 UX / map (P2-P4)

| Area | Candidate hooks | Why |
|---|---|---|
| Map FOW | `MapChunkDatabase` (partial via FOW API) | Production explore rules |
| Map UI / XUi | map window controllers, NCalc bindings | Lon/lat, discovered cities list |
| NavObject | already reflection register | Keep; class via XML |
| Compass | optional | Direction to city |
| Console | `ConsoleCmd*` already | Add `relonlat`, session dump |

### 3.6 Multiplayer (P2+)

| Area | Candidate hooks | Why |
|---|---|---|
| Connection / world ready server | server start, client join | Enforce SharedFixed / same expand |
| Entity pos packages | encode pos (research: teleport thresholds) | Tall Y / large X after expand |
| Chunk send | mesh/chunk packages | Bandwidth under tall columns |

**Do not** patch combat resolution to invent private worlds.

### 3.7 What Harmony cannot replace

- Full-planet data volume → **E + CDN**  
- Legal DEM/pop sources → **E + ATTRIBUTION**  
- Host FPS of 1000 entities → **F measure + optimizer**, not more inject  
- Google-style 3D cities → **forbidden / out of scope**

---

## 4. XML modlet surface map (what to add)

Use **XPath append/set** against live `Data/Config/*` (diff every game update). Prefer small patches over full file replace.

### 4.1 Must-have support modlets (when Streamed/Baked is playable)

| Config file | RealEarth purpose | Notes |
|---|---|---|
| **`nav_objects.xml`** | City name class | **Already** |
| **`biomes.xml`** | Real climate bands if stock ids insufficient | Currently stub note only; either paint `biomes.png` offline or XPath properties (temp, spawn, …) |
| **`rwgmixer.xml`** | Baked/RWG hybrid township density | Stub; **only** if still using RWG city placement |
| **`spawning.xml` / `entitygroups.xml` / `gamestages.xml`** | Density-linked pressure | Scale metro vs plains without Harmony if possible |
| **`blocks.xml` / `materials.xml`** | Optional tall-build / terrain materials | Only if inject needs custom blocks |
| **`worldglobal.xml` or sandbox-related** | Fall damage, world bounds, day length | Soft retunes after expand |
| **`weather.xml` / biome weather** | Lat/biome climate | Soft fidelity |
| **`quests.xml` / trader XML** | Optional “find city” quests | Not required for 1:1 geography |
| **`Localization.csv`** | UI strings for RealEarth windows | When globe XUi exists |
| **`XUi_InGame/*`** | Globe, lon/lat HUD, map overlays | V3 XUi: `XUi_InGame`, `templates.xml`, `{% %}` bindings |
| **`XUi_Menu/*`** | New Game hints for RealEarth worlds | Soft |
| **`shapes` / prefabs** | Custom POI kits for metro bands | Content pack, not core inject |

### 4.2 What XML cannot do (do not pretend)

| Task | Wrong tool | Right tool |
|---|---|---|
| Raise YDim past 255 | XML | **A** binary |
| Sample Copernicus DEM in Streamed | XML | **B + E** |
| Slide host origin / wrap lon | XML | **Sys + B** |
| Measure urban edge from density | XML | **E + Sys** |
| Fix byte height loss | XML | **B** inject int/float + **A** |

### 4.3 Third-party modlets (optional companions, not core)

| External | Role | Relationship to RealEarth |
|---|---|---|
| **Custom Height Map Importer** (Nexus / 7daystodiemods) | Baked heightmap + biomes into RWG | Phase 0 / Baked only; **height limit 255** still applies without our expand |
| **Compo Pack / custom POIs** | More prefab variety for density bands | Content companion |
| **SphereII / darkness falls class packs** | Large XML+Harmony ecosystems | Do not merge; learn XPath/XUi patterns only |
| **ServerTools / Allocs map rendering** | Admin map web UI | Ops; not Earth stream |
| **LagShield / optim mods** | Entity budgets | Complementary under load; measure with APM |

RealEarth should **not** depend on third-party C# for terrain inject (version hell). Optional content XML packs can be separate mods.

---

## 5. Binary / install work beyond current YDim expand

| Work | Why | When |
|---|---|---|
| Re-validate expanded IL site list every TFP build | Constants move | Every update |
| Confirm light/sun/density loops use expanded YMask | Tall darkness/crashes | P1 after expand |
| `.7rg` tall column packing | Save bloat / corruption | P1 soak |
| Optional sparse section storage | RAM for planet+tall | P8 / later |
| Refuse load if YDim stock while config demands 1:1 | Operator safety | Easy Harmony check (partially logged today) |
| Dedicated + client hash matrix | MP desync prevention | Ops tooling |

---

## 6. Offline pipeline / data still missing

| Work | Feeds |
|---|---|
| GHSL/WorldPop/built-up production packs | Density stamps, edge radii |
| OSM roads/rivers extract → stamp corridors | Fidelity |
| Urban area polygons (Natural Earth / OSM) → `edge_radius_m` | City discovery |
| Antimeridian-safe region builder | Pacific packs |
| Lat-corrected spacing for stamps | High-lat cities |
| Reproducible manifests (URL, hash, license, params) | Audits |
| Planet tile farm + CDN layout | Streamed planet |
| Seam / no-data DEM policy | Fail closed |
| 1 m/block regional bakes (not only 30-120 m demos) | Product 1:1 claim |

No Harmony required for pure pack quality; **runtime still needs inject** to show packs.

---

## 7. Recommended build slices (what to add next)

### Slice 1: Terrain truth (Blocker) - **measured green 2026-08-29**

1. Live retarget height + `GenerateTerrain` on 3.2.0 (B): **Done** (heightQ=7 gen=4, failed=0).
2. H500, Everest, and trench soaks (A+F): **Done** (per-chunk inject to `sessionPeak=8778`; below-sea `gameY=5000`; collision/mesh records still open).
3. Biome paint path after height (B + E biomes.png / landcover): **Partial** (inject writes per-column `SetBiomeId` from landcover; decoration/sleeper layers open).
4. Console proof: `reheight` matches sea+elev: **Done**.

**Modlets:** none required beyond existing; optional biomes XPath if IDs need tuning.

### Slice 2: Continuous travel

1. SoloSlide live proof + re-pin cities (Sys, already partial): **Open** (window/wrap moves).
2. Fail-closed missing tiles (Sys): **Done** (live `failClosed=True`).
3. Session save/load origin + AbsoluteXZ (B save hooks + Sys): **Done** (restart restored `absolute=(255,280)`).
4. Document lon/lat limits (done: `LON_LAT.md`).

**Modlets:** none core.

### Slice 3: Places feel real

1. Density stamps with surface Y (B prefab + D prefabs.xml / runtime stamps).  
2. Sleeper Y validation (B).  
3. XML spawn/gamestage scales by biome (C).  
4. City labels edge from pack density (done path; more map data E).

**Modlets:** `spawning` / `gamestages` / denser `nav_objects` optional; `rwgmixer` only for Baked hybrid.

### Slice 4: Multiplayer co-located

1. SharedFixed config enforcement on dedicated (B + config): **Done** (live `mpOrigin=SharedFixed`; loadgen bots joined).
2. Loadgen soak tall Y + density (F): **Partial** (4-6 bots on Everest/trench; multi-bot distance proof open).
3. Same expand both ends (A ops): **Done** (client + dedicated YDim=32768).

**Modlets:** serverconfig/sandbox notes, not geography.

### Slice 5: UX

1. XUi_InGame lon/lat + globe sketch (C + B).  
2. Production FOW (B config).  
3. Persist discoveries (Sys).

### Slice 6: Scale / fidelity later

Roads, rivers, sparse Y, CDN planet farm, geodesic metrics.

---

## 8. Suggested module packaging (future)

Keep one mod folder if possible; split only when load order or optional content demands it.

```text
Mods/
  0_TFP_Harmony/                 # stock: never delete
  RealEarth/                     # core: DLL + JSON + nav_objects + Tools expand
  RealEarth_Content/             # optional: extra prefabs, Localization, XUi globe
  RealEarth_Difficulty/          # optional: gamestages/spawning metro scales
```

| Module | Layer |
|---|---|
| Core RealEarth | A tools + B DLL + Sys + minimal C (`nav_objects`) |
| Content | C + D prefab kits |
| Difficulty | C only |
| Never ship second Harmony | B loads `0Harmony` only |

---

## 9. Evidence checklist (close gaps honestly)

| Claim | How to prove |
|---|---|
| Height inject works | Walk Streamed pack; `reheight` = sea+elev; no stock noise |
| Expand works | `engine-audit` YDim=32768; H500 peak; Everest peak; trench floor |
| Slide works | Log origin slide; player stays; cities re-pin; no wrong DEM |
| Save works | Quit/rejoin same lon/lat and builds |
| MP works | Two clients SharedFixed; shoot; same terrain |
| City edge works | Approach measured edge; name at center only then |
| FPS OK | APM + loadgen under density caps |

Until measured, status stays **Partial / Needed**, not Done.

---

## 10. Anti-scope (explicit)

| Do not build as RealEarth | Why |
|---|---|
| Second multiplayer stack | Vanilla shared XZ is correct |
| Full multithreaded sim rewrite | optimizer / research only |
| Photogrammetry / Google Earth bulk | Policy + legal |
| Replace all stock biomes with 200 climate classes day one | Soft fidelity; landcover map first |
| Depend on SphereII / DF for inject | Coupling death on TFP update |
| Host CCD/NUMA as “mod features” | Ops docs only |

---

## 11. Cross-links

Hub + ownership: [INDEX](INDEX.md). Status: [MODIFICATIONS](MODIFICATIONS.md). Ideas: [DESIGN §18](../DESIGN.md).

---

## 12. One-page answer

**What else is missing?**  
Almost everything that turns “DEM sample in a window” into a durable game: complete inject, tall-Y soak, origin save/reload, build deltas, fail-closed tiles, biome/POI/sleeper on real surfaces, MP shared-origin proof, density budgets, lat-correct metrics, and optional roads/climate/globe UX.

**Which 7D modding APIs do we use?**  
**IModApi + Harmony + binary YDim expand + packs**; XML/XUi support; WebMod/Telnet ops. Full matrix: **§0**.

**What modlets do we add?**  
Support XML only: keep `nav_objects`; add real **biomes/spawn/gamestage/weather/XUi** patches as fidelity and UX land. Stubs today are not product.

**What Harmony do we add?**  
Expand RealEarth’s single DLL: finish **height + GenerateTerrain**, then **biome paint, decoration/POI Y, save/load session, chunk delta, light/stability if broken**, then **map/XUi** and **MP guardrails**. Discover targets from live `Assembly-CSharp` using research dumps as a checklist.

**What binary work remains?**  
Y expand validation, light/Y-mask completeness, save format, optional sparse Y later. Re-apply after every Steam update on **client and dedicated**.

## Related docs

| Doc | Role |
|---|---|
| [MODIFICATIONS](MODIFICATIONS.md) | Status only |
| [IMPLEMENTATION_PLAN](IMPLEMENTATION_PLAN.md) | P0-P8 |
| [realearth-runtime](realearth-runtime.md) | Streamed lessons |
| [research INDEX](../../7dtd-engine-research/docs/INDEX.md) | Generic RE |

## Changelog

- **2026-07-19:** Ownership header; related docs.
