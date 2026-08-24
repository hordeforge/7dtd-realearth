# RealEarth research notes

**Owns:** living research notes (may be stale vs hubs).  
**Not:** canonical status ([MODIFICATIONS](MODIFICATIONS.md)); prefer INDEX hubs for current truth.  
**Hub:** [INDEX](INDEX.md).


Living notes for the RealEarth 7DTD project. 
**Last updated:** 2026-07-15 

**Target game:** 7 Days to Die **V3.1.0 Stable** (“Henpocalypse” line)

Sources: official site blogs, TFP forums, wiki.gg, 7daystodiemods.com, Steam guides, Nexus, community reports. 
Modding site index: [MODDING_REFERENCES.md](MODDING_REFERENCES.md). 
Re-verify Harmony targets and XML paths against a live install after every major patch.

---

## 1. Version timeline (relevant to this project)

| Date (approx) | Version | Codename / focus | Notes for RealEarth |
|---|---|---|---|
| 2024-06 | 1.0 / A22 | Full release | Modern RWG baseline |
| 2025-06+ | 2.0-2.4 | 2.x era | Biome hazards, storms mature |
| **2025-12-12/18** | **2.5** | **Survival Revival** | Jars, smell, 3rd person, temp/clothing, apiary, RWG tweaks |
| **2026-04** | **2.6** | Stability | City hitch fixes, jar refund default 60%, snow/wasteland harder, RWG tile tweaks |
| **2026-03** | Studio | TFP joins Behaviour Interactive | More resourcing expected; TFP still leads design |
| **2026-06** | **3.0** | **Dead Hot Summer** | 150 sandbox options, Magnitude, Sign-Tech, 60+ POIs, **modding breaks**, RWG perf |
| **2026-07** | **3.0.1** | Stable hotfix | Sign-Tech, cosmetics, airdrop night, RWG preview crash, region edge cases |

**Pin RealEarth to 3.1.0.** Do not claim 3.0.1 as current.

Official index: https://7daystodie.com/ 
News & announcements: https://community.thefunpimps.com/forums/news-announcements.7/

### Key official posts

- V3.0.1 Stable: https://7daystodie.com/v3-0-1-stable-release/ 
- V3.0 Dead Hot Summer notes: https://7daystodie.com/v3-0-dead-hot-summer-release-notes/ 
- V2.6 Stable: https://7daystodie.com/v2-6-stable/ 
- 2.5 Survival Revival: https://7daystodie.com/2-5-survival-revival-update/ 
- TFP × Behaviour: https://7daystodie.com/tfp-joins-behaviour-interactive/ 
- Forum 3.0.1: https://community.thefunpimps.com/threads/v3-0-1-stable.48230/

---

## 2. What V3.0 actually changed (mod-relevant)

### 2.1 Sandbox system

- ~**150** sandbox options (player, entity, world, resource, crafting, traders, tasks, misc).
- Official presets: Undead Matinee, Madmole’s Mayhem, Almost Creative, Bite Club, Legacy Survival, 7 Days Later, Caveman’s Life, Dumpster Diver, Dying World, Disaster Film, Chibi Mode, etc.
- Servers: many legacy `serverconfig.xml` keys removed; replaced by:
 ```xml
 <property name="SandboxCode" value="AAAJABJACJADJARFBNC"/>
 ```
 (example default “Adventurer” equivalent from TFP notes).
- Migrating V2.6 servers: recreate settings in-game, copy SandboxCode into serverconfig.
- Community tools exist to generate codes (e.g. host panels / sandbox code generators).

**RealEarth:** ship a recommended SandboxCode (map/compass on for globe UX, storms on for climate immersion, optional high enemy density in urban pop tiles later).

### 2.2 Itemization: Magnitude + Combine Station

- Looted tools/weapons can roll **boosted stats** (orange star + teal %).
- Mods gain quality tiers (Q1-Q6 progressive bonuses).
- **Combine Station** merges best quality/stats/durability; also repair path.
- Repair degradation sandbox-tunable.

**RealEarth:** no direct map impact; urban loot density should still feel worth megacity risk.

### 2.3 Sign-Tech + POIs

- New sign system for POI creators (canvas/decal, layers, warps, RGBA).
- **60+ new POIs** (T4/T5 industrials, farms, army camps, stadium, etc.).
- Extra RWG tiles for 100×100 commercial/industrial.

**RealEarth:** use new POIs as stamp packs for population bands (`metro` / `large_city` / `town`).

### 2.4 UI

- **Main menu redesigned** in 3.0.
- **Full in-game HUD overhaul still pending** (TFP stated future release).
- Crosshair customization (scale, opacity, color, when shown).

**RealEarth globe map:** implement as modular XUi window; expect another UI break when full HUD ships.

### 2.5 RWG / terrain engine (3.0 changelog highlights)

Added/changed:

- RWG biome layout **“Circle 2”** (doubles each biome ring style).
- RWG preview: terrain step, biome preview ASAP, generate-as-task (UI stays alive), cancel during gen.
- New **district creation algorithm**.
- Optimized: stamp loading, radiation memory, water data, stamping speed, height copying, preview mesh.
- Reduced rural tile percents; new commercial/industrial spawn opportunities.
- **Optimized chunk mesh generator**.
- **NEW_WATER_MESH** define on by default (better water meshes/perf).
- Height map processing fixes (lowering terrain, prefab underground heights).
- Continue Game: full reset of **unprotected chunks**; server command for same.
- Warning when loading save from older major version.
- PC XBL cloud saves option for worlds/saves.

**RealEarth:** finite RWG is better, not infinite. Streaming architecture remains mandatory for planet scale.

### 2.6 Graphics / platform

- DirectX 12 supported on Windows (not default).
- Mac: Metal default.
- DualSense Edge better support.

### 2.7 Known issues / community after 3.0.1

- Some dedi hosts: Region folder spam / corruption reports on **pre-3.0 worlds** after upgrade (not always new 3.x worlds).
- Server RAM growth / restart culture still common.
- Steel wall cabinets lock issue reported (staff: not intentional).
- Mods must update for 3.0.1; some players stay on 3.0.0 until mods catch up.

---

## 3. Survival systems still in force (from 2.5/2.6)

These affect how a real-Earth climate map should feel:

| System | Behavior | RealEarth hook |
|---|---|---|
| **Empty jars** | Early scavenge jars, murky water, boil; craft jars mid-game; refund % sandbox | Natural water bodies matter |
| **Smell** | Raw meat, some food, dysentery; reduced indoors; water/rain clears | Cities with meat loot smell-dense |
| **Temperature** | Hot/cold stages; clothing insulation; altitude reduces temp | Compress elevation carefully; snow lat bands |
| **Storms** | Per-biome, grace period by clothing, aggressive zombies, more loot | Landcover/climate should drive storm biomes |
| **Biome hazards** | Ash, sand, cold air, toxic fallout independent of storms | Map landcover → forest/desert/snow/wasteland/burnt |
| **3rd person** | Full toggle + server restriction | Globe UI independent |
| **Apiary** | Honey station | Rural/farm stamps |

2.6 defaults worth noting: jar refund **60%**, dew collector needs jars as fuel, snow GS modifier 3, wasteland 5.

---

## 4. World / map technical constraints

### 4.1 Scale facts

| Fact | Value |
|---|---|
| Block size | **1 m³** |
| Typical RWG sizes | 4k, 6k, 8k, 10k common; larger via mods/configs historically |
| Practical SP sweet spot (community) | 6k-8k |
| Game height | Stock **~0-255**; RealEarth product uses YDim expand + real meters (not compress-into-255) |
| Full Earth 1:1 width | ~40,075,017 blocks |
| Vanilla does **not** support spherical topology | Flat rectangle only |

Historical note: very large maps (old 30k talk) balloon save sizes into tens of GB; city hitch fixes in 2.6/3.0 help but density still expensive.

### 4.2 Save / region files

Observed layout (paths vary slightly by platform):

```
%AppData%/7DaysToDie/
 GeneratedWorlds/<WorldName>/ # generated map assets (biomes.png, prefabs.xml, …)
 Saves/<WorldName>/<GameName>/
 Region/r.X.Y.7rg # binary terrain + player changes
 Player/*.ttp
 main.ttw
 players.xml
```

- Extension: **`.7rg`** region files (`r.x.y.7rg`).
- Header structure is brittle (community validators fix 64-byte headers).
- Delete one region → regenerates that area (loses player builds there).
- V3.0: unprotected chunk reset commands for “Continue Game” style refreshes.

**RealEarth deltas:** store player edits as overlays keyed by earth tile, or accept vanilla `.7rg` within local window only.

### 4.3 Generated world assets (post-RWG)

Common files under `GeneratedWorlds/<name>/`:

- `biomes.png` - exact palette only
- `prefabs.xml` - placed POIs/traders (edit **before first load**)
- radiation / splat / height-related assets depending on version
- Preview meshes for RWG UI

### 4.4 Biome map colors (vanilla-style)

Community consensus (v1.0 guide, still widely used): **only pure vanilla biome colors** work when hand-editing `biomes.png`. Do not anti-alias.

Exact RGB must be color-picked from a real generated `biomes.png` on **3.0.1** (do not invent). Historically five playable biomes:

1. Forest 
2. Burnt forest 
3. Desert 
4. Snow 
5. Wasteland 

Water is handled as water/height, not always as a sixth paint color in the same way.

**Action item:** On first game install, dump palette:

```bash
# after generating any small RWG world
# open GeneratedWorlds/*/biomes.png, sample unique RGB, write into landcover.py BIOME_RGB
```

Update `tools/realearth/landcover.py` to match exact 3.0.1 values (current code uses approximate placeholders).

### 4.5 Heightmaps for custom importers

Nexus **Custom Height Map Importer** (updated for 2.5; re-check for 3.0.1):

- Common size: **8192×8192**
- Format: **16-bit grayscale PNG** named `heightmap.png`
- **Height limit 255 blocks**

Our exporter already writes 16-bit `heightmap.png` + 8-bit variant + `biomes.png` + preview.

### 4.6 RWG design rules (community, still useful)

From serious map-crafting guides (v1.0, still conceptually valid):

- Mountains % strongly reduces town count (keep mountains ≲20% for dense cities).
- **Largest cities favor wasteland** in default mixer rules.
- Forest / burnt forest: fewer large towns by default.
- Seed + size define outer boundary (ocean/mountain edges); same seed ≠ same boundary at different sizes.
- Post-gen: edit `biomes.png`, verify traders in `prefabs.xml` before first enter.
- Deep control: `Data/Config/rwgmixer.xml` (township counts, district weights, trader biome tags). **Backup first.** V3.0 nested XML / district algorithm may differ; re-diff against 3.0.1 file.

**RealEarth population stamping** should override vanilla “wasteland = big city” bias with real urban locations.

---

## 5. Modding surface (3.0.1)

### 5.1 Install layout

```
7DaysToDie/Mods/
 0_TFP_Harmony/ # VANILLA - never delete
 RealEarth/
 ModInfo.xml
 RealEarth.dll # optional C#
 Config/ # XPath XML patches
 Data/ or Resources/
 UIAtlases/ # icons if needed
 XUi_* patches # via Config xpath or full overrides carefully
```

User mods go in game `Mods/` or sometimes `%AppData%/7DaysToDie/Mods/` depending on launcher; PC Steam usually game dir.

### 5.2 ModInfo.xml

Modern form (A21+ style still used): Name, DisplayName, Description, Author, Version, Website as XML attributes/values.

### 5.3 C# / Harmony

- Game ships **0Harmony** via `0_TFP_Harmony`.
- Reference `Assembly-CSharp.dll` + `0Harmony.dll` from `7DaysToDie_Data/Managed/` with Copy Local = false.
- **3.0:** WebDashboard integrated into core → mods only need core assembly.
- Publicizer: overrides of vanilla methods may need **public** visibility adjustments.
- Entry: class implementing `IModApi` with `InitMod(Mod mod)`.
- Register custom XUi bindings early in `InitMod` (see wiki).

### 5.4 XML / localization breaks in 3.0

| Change | Action |
|---|---|
| `Localization.txt` → **`Localization.csv`** | Ship CSV |
| `entitygroups.xml` → structured XML | Prefer elements; old text still accepted temporarily |
| Pipe `|` multi-properties → nested classes | Update patches |
| `Map.Color` → `MapColor` | Rename |
| `XUi/` → **`XUi_InGame/`** | Patch correct folder |
| `controls.xml` → **`templates.xml`** | Rename |
| Remove `force_hide`; use `visible` | UI XML |
| New views: video, scrollbar, scrollview | Available for globe UI |
| RWG generation XML output class structure | Tooling must adapt |

### 5.5 XUi (wiki.gg, V3.0)

Doc: https://7daystodie.wiki.gg/wiki/XUi 

Folders under `Data/Config/`:

- `XUi_Common` - shared styles/templates 
- `XUi_Menu` - main menu 
- `XUi_InGame` - HUD / gameplay windows 

Each: `styles.xml`, `templates.xml`, `xui.xml`, `windows.xml`.

**Bindings V3.0:**

- New: `attribute="{% ncalc expression }"` - preferred 
- Deprecated: `{# … }` legacy NCalc, `{binding}` simple 
- Typed bindings via `[XuiXmlBinding]` / `[XuiXmlAttribute]` 
- Custom registration: `BindingMethodCache` / `ParsingMethodCache` in `InitMod` 
- Null strings forbidden from bindings 

**Globe map plan:** new window group in `XUi_InGame`, NCalc bindings for player lon/lat, sphere or equirect texture later.

### 5.6 Chunk generation hooks (research TODO on live DLL)

Not fully mapped without decompile of 3.0.1. When game install available, search:

- `ChunkProvider*` / `WorldGeneration` / `TerrainGenerator` / `BiomeProvider`
- Height sampling methods writing density or solid blocks
- `GameManager` / player position for wrap + streamer tick
- Map UI controllers for minimap dual-drive

Document method signatures in `docs/HARMONY_TARGETS_3.0.1.md` once discovered (per-build).

---

## 6. Earth data (offline pipeline)

### 6.1 Elevation

| Source | Resolution | Notes |
|---|---|---|
| Copernicus DEM **GLO-30** | ~30 m | Production choice; registration/terms |
| SRTM | 1-3 arcsec | Public domain US product |
| AWS Terrain Tiles / Terrarium | Web tiles | Progressive; decode RGB formula |
| Open-Meteo Elevation API | Point samples | Fine for **small demos only** (rate limits) |
| Synthetic | N/A | Offline CI / tests |

Terrarium decode: 
`elev = R*256 + G + B/256 - 32768`

### 6.2 Land cover / climate

| Source | Use |
|---|---|
| ESA WorldCover (10 m) | Landcover → biome paint |
| Dynamic World / MODIS | Alternatives |
| WorldClim / Köppen | Climate refine snow/desert/forest |

### 6.3 Population / cities

| Source | Use |
|---|---|
| WorldPop / GHSL | Density raster → tile channel |
| Natural Earth populated places | Settlement points |
| GeoNames cities500/1000 | Names + pop |
| OSM (ODbL) | Roads, waterways, buildings outlines |

Population bands (project convention):

| Pop | Band | Stamp intent |
|---|---|---|
| ≥1M | metro | multi-block city pack |
| ≥100k | large_city | dense prefabs |
| ≥10k | town | township |
| ≥1k | village | small cluster |
| ≥100 | hamlet | sparse cabins/farms |
| &lt;100 | rural_scatter | isolated POIs |

Same ladder in `settlements.py::Settlement.band` (pack writer) and
`RuntimePoiInject.BandFromPop` (runtime fallback); band picks the prefab pool,
so both must agree.

### 6.4 Licensing checklist

Ship `ATTRIBUTION.md` with every tile pack. OSM ODbL share-alike applies to derived DBs. Do not redistribute restricted DEMs; point pipeline at user downloads.

### 6.5 Scale / storage math (planning)

Assume 512² tiles, 1 m/sample, full Earth:

- Tiles X ≈ 78,272; Z ≈ 39,071 → **~3.06e9 tiles** (impossible as full local set).
- Strategy: region packs, continental farms, CDN streaming, multi-res pyramids (30 m global, 1-5 m cities).

At **30 m/sample**, linear dimensions shrink ×30 → still huge but continent slices become tractable.

At **100 m/sample**, country-scale packs fit hobby machines.

---

## 7. Architecture decisions (confirmed by research)

1. **Do not** prebuild one global heightmap for 1:1 Earth. 
2. **Do** use virtual equirectangular grid + **tile streaming** + **sliding origin**. 
3. **Longitude wrap** implements “go around the Earth”; poles clamp. Distortion, dual coords, and gaps: `docs/LON_LAT.md`. 
4. **Real height** requires YDim expand (1 m = 1 block); do not productize compress-into-255. 
5. **Phase 0 playable path:** heightmap + biomes PNG for importer / RWG hybrid. 
6. **Phase 2+:** Harmony chunk fill from `.rte` tiles. 
7. **Globe minimap:** XUi_InGame + NCalc bindings; sphere preferred, equirect fallback. 
8. **Player builds:** delta overlays or local-window `.7rg` only. 
9. **Target API:** 3.0.1; re-diff every patch. 
10. **Cities:** real coordinates + density, not vanilla wasteland-city bias.

---

## 8. Competitive / prior art

| Project | Relevance |
|---|---|
| Custom Height Map Importer (Nexus) | Phase 0 install path |
| Nitrogen / KingGen (legacy) | Older external generators; RWG largely replaced them |
| Large-map modlets (16k RWG menus) | Shows demand; still finite |
| Community biomes.png editing | Validates post-gen paint workflow |
| Region validators (`.7rg` header fix) | Ops tooling for large worlds |

No known maintained **true planetary streaming** 7DTD mod as of research date. RealEarth is greenfield at that layer.

---

## 9. Community pain points (design around them)

- City FPS / hitching (improved 2.6/3.0, still careful with metro stamps). 
- Save/region corruption on long dedi runs → auto-backup deltas. 
- Mod breaks every major version → versioned Harmony profiles. 
- SandboxCode opaque for servers → document + link generator. 
- Biome paint must be exact RGB. 
- Vertical scale disappointment if users expect Everest meters → educate in UI/README.

---

## 10. Action checklist (research → engineering)

### Immediate

- [x] Pin target version **3.0.1** in notes (superseded: product now pinned to **3.1.0**, see §Version) 
- [x] Update README/DESIGN version strings (now **V3.1.0**, not 3.0.1) 
- [ ] Color-pick real `biomes.png` on 3.0.1 install → fix `landcover.py` 
- [ ] Verify Custom Height Map Importer works on 3.0.1 (or find successor) 
- [ ] Diff `rwgmixer.xml` / biomes.xml from 3.0.1 vs our assumptions 

### With game install

- [ ] Map Harmony targets for terrain/chunk gen (write `HARMONY_TARGETS_3.0.1.md`) 
- [ ] Prototype XUi globe window with `{% %}` bindings 
- [ ] Measure memory for N hot tiles (512² elev+lc+pop) 
- [ ] Test longitude wrap edge cases (entities, vehicles, land claims) 

### Data

- [ ] Script Copernicus/SRTM tile farm for one country at 30 m 
- [ ] Ingest Natural Earth + WorldPop for city density validation 
- [ ] OSM road raster or vector POI channel prototype 

### Product

- [ ] Recommended SandboxCode for “RealEarth Immersion” preset 
- [x] In-game city map labels: discover at city edge, pin at center (see `docs/CITY_MAP_LABELS.md`)
- [ ] Discovery system: unlock globe UI cities when tiles visited (beyond map NavObjects) 
- [ ] Multiplayer: shared tile pack hash + delta sync design 

---

## 11. Open questions

1. Exact 3.0.1 world size enum values and hard max without mods? 
2. Can heightmaps larger than 8k be imported reliably on 3.0.1? 
3. Is water in biome map still special-cased or height-only? 
4. Land claim / trader protection behavior across sliding origin remaps? 
5. Does 3.0 chunk mesh optimize change multiplayer authority for custom height writes? 
6. Behaviour Interactive roadmap: any infinite-world tech reuse? (unknown; watch blogs) 

---

## 12. Modding websites (see full index)

**Canonical list:** [MODDING_REFERENCES.md](MODDING_REFERENCES.md)

| Site | Role |
|---|---|
| [7daystodiemods.com](https://7daystodiemods.com/) | Primary 7D2D mod hub, install guides, Harmony warning, distribution |
| [7d2dmodding.wiki.gg](https://7d2dmodding.wiki.gg/) | V3.0-focused modding wiki (XPath, Harmony targets, sandbox code) |
| [7daystodie.wiki.gg](https://7daystodie.wiki.gg/wiki/Modding_Resources) | Official wiki modding resources + XUi docs |
| [Nexus 7DTD](https://www.nexusmods.com/7daystodie) | Alt distribution / heightmap tools |
| TFP forums | XPath thread, news, resources |
| Guppy / modding Discords | Live author help |

## 13. Source log

| Source | Used for |
|---|---|
| 7daystodie.com V3.0 / V3.0.1 / V2.6 / 2.5 / Behaviour posts | Version features, modding notes |
| community.thefunpimps.com V3.0.1 thread | Hotfixes, save advice, server issues |
| 7daystodie.wiki.gg XUi + Modding Resources | Bindings, tutorials, Discord |
| 7d2dmodding.wiki.gg | V3.0 Harmony/XPath/sandbox references |
| 7daystodiemods.com | Install layout, Harmony folder, publish target |
| Steam Random Map Guide 1.0 (Serious) | RWG workflow, biomes.png rules, rwgmixer |
| Nexus Custom Height Map Importer | heightmap.png 16-bit, 255 height, 8k |
| Community region/.7rg posts | Save layout, corruption ops |
| Prior RealEarth DESIGN.md | Coordinate + streaming plan |

When adding new findings, append a dated subsection under the relevant heading and bump **Last updated**.

## Related docs

| Doc | Role |
|---|---|
| [INDEX](INDEX.md) | Product hub (prefer) |
| [RESEARCH_LOG](RESEARCH_LOG.md) | Chronology |
| [realearth-runtime](realearth-runtime.md) | Current Streamed lessons |

## Changelog

- **2026-07-19:** Ownership header; related docs.
