# 7DTD modding references

**Owns:** external modding site pointers.  
**Not:** product install ([MODLET](MODLET.md)), engine RE ([research INDEX](../../7dtd-engine-research/docs/INDEX.md)).  
**Hub:** [INDEX](INDEX.md).


Living index of community + official modding sites for **RealEarth**.  
**Last updated:** 2026-08-09 · Target game **V3.1.0**

**Practices and boundaries (workspace-wide):** see
[`../../MODDING_BEST_PRACTICES.md`](../../MODDING_BEST_PRACTICES.md).

Use these as first-class references when packaging the mod, writing Harmony patches, XPath, XUi, or checking how other large world/UI mods ship.

---

## Primary distribution & community sites

### 1. [7DaysToDieMods.com](https://7daystodiemods.com/)

Largest **7D2D-focused** independent mod platform (not multi-game like Nexus).

| | |
|---|---|
| **Home** | https://7daystodiemods.com/ |
| **About** | https://7daystodiemods.com/about |
| **Install guide** | https://7daystodiemods.com/posts/how-to-install-7-days-to-die-mods |
| **Harmony warning** | https://7daystodiemods.com/posts/stop-deleting-the-harmony-folder |
| **Discord** | https://discord.gg/cCsGJjkkwC |
| **X / Twitter** | https://x.com/7DaysToDieMods |

**Why it matters for RealEarth**

- Default place players look for 3.0.x mods and version tags (V2 / V3 filters).
- Install path conventions match ours: `Mods/<ModName>/ModInfo.xml` under the game install.
- **Never delete `0_TFP_Harmony`** (vanilla; C# mods need it). Document this in our install README.
- Safe hosting + creator pages: good target if/when we publish a downloadable RealEarth package.
- Tracks game news (e.g. V3.0.1 Stable posts) next to mods.

**Install rules they emphasize** (confirm on live guide; paraphrase)

1. Download mod zip.
2. Extract so **`ModInfo.xml` is immediately under** `Mods/RealEarth/`, not nested extra folders.
3. Keep `Mods/0_TFP_Harmony/` intact.
4. Launch game; check log if mod missing.

---

### 2. [Nexus Mods: 7 Days to Die](https://www.nexusmods.com/7daystodie)

| | |
|---|---|
| **Browse** | https://www.nexusmods.com/7daystodie |
| **Example tooling** | Custom Height Map Importer and other world tools often land here |

**Why it matters**

- Alternate distribution; many technical/utility mods.
- Heightmap importer path for Phase 0 still often discovered via Nexus.
- Articles (e.g. basic troubleshooting) linked from official wiki resources.

---

### 3. Official TFP surfaces

| | |
|---|---|
| **Forums** | https://community.thefunpimps.com/ |
| **News & announcements** | https://community.thefunpimps.com/forums/news-announcements.7/ |
| **Tutorials & guides** | https://community.thefunpimps.com/forums/tutorials-guides.39/ |
| **XPath explanation (sphereii)** | https://community.thefunpimps.com/threads/xpath-modding-explanation-thread.7653/ |
| **Mods/resources section** | https://community.thefunpimps.com/resources/ |
| **Site / blogs** | https://7daystodie.com/ |
| **Official Discord** | https://discord.gg/taYNEUS |

---

## Documentation wikis

### 4. [7D2D Modding Wiki (wiki.gg)](https://7d2dmodding.wiki.gg/)

Community wiki aimed at **V3.0** documentation.

| Page | URL | Use for RealEarth |
|---|---|---|
| Home | https://7d2dmodding.wiki.gg/ | Index |
| Getting Started | https://7d2dmodding.wiki.gg/wiki/Getting_Started | Onboarding structure |
| XML File Index | https://7d2dmodding.wiki.gg/wiki/XML_File_Index | Which configs to patch |
| XPath Cheat Sheet | https://7d2dmodding.wiki.gg/wiki/XPath_Cheat_Sheet | Config/ XPath |
| Harmony Patch Targets | https://7d2dmodding.wiki.gg/wiki/Harmony_Patch_Targets | Chunk/world hooks |
| Sandbox Code Generator | https://7d2dmodding.wiki.gg/wiki/Sandbox_Code_Generator | Recommended SandboxCode |
| World & Environment | https://7d2dmodding.wiki.gg/wiki/Category:World_%26_Environment | RWG / POI / terrain |
| UI & HUD | category UI | Globe minimap |
| Version Notes | category Version_Notes | 3.0 breakages |
| Discord | https://discord.gg/WeDEvUkR9t | Modding help |

---

### 5. [Official 7DTD Wiki: Modding](https://7daystodie.wiki.gg/)

| Page | URL | Use |
|---|---|---|
| Modding hub | https://7daystodie.wiki.gg/wiki/Modding | Overview |
| Mod Interface | https://7daystodie.wiki.gg/wiki/Mod_Interface | Load paths, structure |
| Modding Resources | https://7daystodie.wiki.gg/wiki/Modding_Resources | Tutorials, GitHub, Discord |
| **XUi (V3.0 bindings)** | https://7daystodie.wiki.gg/wiki/XUi | Globe UI / NCalc `{% %}` |
| Fandom Mod Structure (legacy mirror) | https://7daystodie.fandom.com/wiki/Mod_Structure | Folder layout history |

Local game files remain the ground truth:

```
<Install>/Data/Config/          # vanilla XML + XML.txt notes
<Install>/Data/Config/XUi_*/    # XUi_Common, XUi_Menu, XUi_InGame
<Install>/Mods/0_TFP_Harmony/
```

---

## Discord / live help

| Community | Invite / note |
|---|---|
| **Guppycur’s Unofficial 7DtD Modding** | https://discord.gg/WpVPJWj7Xk (read `#welcome` first) |
| **7d2d Modding Wiki Discord** | https://discord.gg/WeDEvUkR9t |
| **7DaysToDieMods.com Discord** | https://discord.gg/cCsGJjkkwC |
| **TFP official** | https://discord.gg/taYNEUS |

---

## Learning paths (linked from official resources)

| Resource | Topic |
|---|---|
| MaxFox Gaming A21 XML series | XPath / modlets from zero |
| sphereii A20 + GitHub SphereII.Mods | C# / project setup |
| Fubar Prime (TFP) XML playlist | Official XML power |
| Phys1csGamez prefab series | POI stamps for cities |
| Harmony docs | https://harmony.pardeike.net/articles/intro.html |
| DarkAoRaidenX XPath tutorial | https://darkaoraidenx.github.io/7DTD/introduction.html |
| Templates | https://github.com/7D2D/Templates-and-Utilities |
| Unity scripts | https://github.com/7D2D/Unity-Scripts |

---

## Related tools / prior art to watch on those sites

Search 7daystodiemods.com + Nexus for version **3.0 / 3.0.1**:

| Kind | Why watch |
|---|---|
| Custom heightmap / RWG size mods | Phase 0 install path for our PNG export |
| HUD / map UI mods (e.g. HUDPlus lineage) | Patterns for globe/local map XUi |
| Large overhauls (server-side vs client) | Packaging, EAC notes, load order |
| Prefab / POI packs | Metro/town stamp content |
| WalkerSim / AI world tools (GitHub) | Streaming/AI ideas (not copy) |

---

## RealEarth vs other 7D modding APIs

Decision matrix (when to use XPath, IModApi, Harmony, XUi, WebMod, binary expand, bake path, and what third-party mods use): **[GAP_HARMONY_MODLETS.md](GAP_HARMONY_MODLETS.md)** §0.  
Workspace layer rules: [`../../MODDING_BEST_PRACTICES.md`](../../MODDING_BEST_PRACTICES.md).

---

## RealEarth packaging checklist (from site conventions)

```
Mods/RealEarth/
  ModInfo.xml                 # required; folder name = mod id
  RealEarth.dll               # C# optional until Harmony wired
  Config/                     # XPath patches mirroring Data/Config
  Config/realearth.json       # our runtime config
  Data/tiles/                 # tile pack or pointer
  Localization.csv            # 3.0+ (not .txt)
  UIAtlases/ …                # if custom icons
```

- **Do not** ship a nested `RealEarth/RealEarth/ModInfo.xml` zip mistake (common install fail called out on 7daystodiemods).
- **Do not** overwrite or delete `0_TFP_Harmony`.
- Tag releases with **game version** (3.0.1) on 7daystodiemods / Nexus.
- Prefer XPath modlets over editing vanilla `Data/Config` in place.

---

## How to use this file in the project

1. Before changing Harmony targets → check [Harmony Patch Targets](https://7d2dmodding.wiki.gg/wiki/Harmony_Patch_Targets) + live `Assembly-CSharp`.
2. Before XUi globe work → [XUi wiki](https://7daystodie.wiki.gg/wiki/XUi) + `XUi_InGame` on disk.
3. Before publish → install guide on 7daystodiemods + version tag + Harmony note.
4. When stuck → Guppy / modding wiki Discord (after reading welcome rules).

Append new useful links below with date.

### Log

- **2026-07-15:** Initial index from 7daystodiemods.com, Nexus, wiki.gg modding wiki, official Modding Resources, Discords.

## Related docs

| Doc | Role |
|---|---|
| [MODLET](MODLET.md) | Install |
| [MODDING_BEST_PRACTICES](../../MODDING_BEST_PRACTICES.md) | Workspace layers |

## Changelog

- **2026-07-19:** Ownership header; related docs.
