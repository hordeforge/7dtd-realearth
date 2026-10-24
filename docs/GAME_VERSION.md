# Target game version

**Owns:** pinned game build and install paths for this machine.  
**Not:** install how-to ([MODLET](MODLET.md), [PROTON_INSTALL](PROTON_INSTALL.md)), product status ([MODIFICATIONS](MODIFICATIONS.md)).  
**Hub:** [INDEX](INDEX.md).

| Field | Value |
|---|---|
| **This machine after Steam update** | **V 3.3.0 (b18)** (dedicated log `Version: V 3.3.0 (b18)`, Compatibility `V 3.3.0`, Build `LinuxServer 64 Bit`; Steam 2026-10-24) |
| **VersionInformation** | `(1, 3, 30, 18)` |
| **Stock wire string** | `V3.3.0 b18` |
| **Steam build id** | 25661908 (dedicated); client app 251570 manifest is 25661859 |
| **Depot 294422 manifest** | `3031329678505041777` |
| **`Assembly-CSharp.dll` (dedicated)** | sha256 `e16ff9d539b8fbf64904c0bc090d502286a62464742a9396f0455936ad0beb87`, 11697152 bytes |
| **`Assembly-CSharp.dll` (client)** | sha256 `fceec27300ffd3a1f97b097e43b60f3b07597f441e7ecbc6e1b59eebb234c705`, 11923968 bytes |
| **Client path** | `~/.local/share/Steam/steamapps/common/7 Days To Die` |
| **Dedicated server** | `…/7 Days to Die Dedicated Server` |
| **Proton userdata** | `…/compatdata/251570/pfx/…/AppData/Roaming/7DaysToDie` |
| **Markers** | `Localization.csv` (3.x), newer `Assembly-CSharp.dll` |

Pins are machine-read; the exhaustive release delta lives in
[`../../7dtd-engine-research/docs/releases/changelog-3.3.0.md`](../../7dtd-engine-research/docs/releases/changelog-3.3.0.md)
§2 and the committed pins in
[`../../7dtd-engine-research/tools/data/stock_facts.json`](../../7dtd-engine-research/tools/data/stock_facts.json).

## After every Steam update

```bash
export SEVENDTD_GAME_DIR="$HOME/.local/share/Steam/steamapps/common/7 Days To Die"
./scripts/install_proton.sh
```

That rebuilds `RealEarth.dll` against the new Managed assemblies and reinstalls:

- `Mods/RealEarth/` (client + dedicated)
- `GeneratedWorlds/RealEarth` under **Proton** Roaming (and native for server tests)

The runtime YDim transpiler (`EngineHeightRuntimePatch=true`) hot-patches the
expand at boot, so Steam Verify does not undo it; re-running `make install`
after an update re-applies the mod.

**3.3.0 retarget note (2026-10-24):** the update replaced `Assembly-CSharp.dll` on
both installs. This build moves every save/network `Read`/`Write` to
`PooledBinaryReader`/`PooledBinaryWriter` (byte-neutral) and bumps the
per-record save versions instead: `EntityCreationData` 37 -> 38,
`TEFeatureStorage` 18 -> 20, `Bag` 1 -> 2, `Equipment` 4 -> 6,
`Quest.FileVersion` 8 -> 9, `.ttp` header 59 -> 62. `main.ttw` stays 23, the
chunk preamble stays 47, the region container is unchanged. Compatibility is
one-way (b18 reads b10; b10 cannot read a b18 save), owned by
[`save-region.md`](../../7dtd-engine-research/docs/world/save-region.md).

RealEarth's Harmony targets were IL-checked against the b18 dedicated assembly:
every reflection target in the documented set (height queries, terrain generate,
chunk index, player tick and unload, world ready/save, longitude wrap) still
exists with an unchanged signature, two postfix bodies grew
(`EntityPlayerLocal.OnEntityUnload` 66 -> 69 IL, `GameManager.StartGame`
21 -> 24 IL), and the `PrefabInstance` ctor / `CopyIntoWorld` /
`PrefabCache.GetPrefab` signatures are unchanged. The client assembly carries
the same targets (checked with `monodis`), so `BuildGuard` now lists both b18
hashes. **Live re-soak on b18 is still open**; what verifies it is step 3 below
plus `[RealEarth] RealEarth init OK` in a client boot.

## Verify

1. Steam → launch 7DTD (Proton)
2. New Game → **RealEarth**
3. Log under Proton `logs/output_log_*.txt` should contain:
   ```
   [RealEarth] RealEarth init OK
   ```

## Notes

- Always build against **this** install’s `Assembly-CSharp.dll`, not a hard-coded version string.
- Keep `Mods/0_TFP_Harmony`.
- C# mods may need EAC off depending on settings.
- Generic engine RE pin: [`../../7dtd-engine-research/docs/meta/coverage.md`](../../7dtd-engine-research/docs/meta/coverage.md).
- V3.3.0 exact-diff changelog: [`../../7dtd-engine-research/docs/releases/changelog-3.3.0.md`](../../7dtd-engine-research/docs/releases/changelog-3.3.0.md) (IL-verified; save records bumped, inventory/equipment reworked, `AssetManagement` and `Services.Analytics` added, console registry 188 -> 190).

## Height expand state (this machine)

With the mod installed (`EngineHeightRuntimePatch=true`), the YDim expand is
hot-patched at boot on both client and dedicated (`ChunkBlockYDim=32768`). No
DLL is edited and no stock backup exists.

Probe with `realearth engine-audit` or regenerate dumps via `DumpTerrain` (see workspace [`7dtd-engine-research/docs/world/terrain-height.md`](../../7dtd-engine-research/docs/world/terrain-height.md)). After a Steam Verify, re-run `make install` to re-apply the mod.

## Related docs

| Doc | Role |
|---|---|
| [PROTON_INSTALL](PROTON_INSTALL.md) | Proton paths |
| [MODLET](MODLET.md) | Install + expand |
| [HEIGHT_LIMITS](HEIGHT_LIMITS.md) | Expand policy |
| [research coverage](../../7dtd-engine-research/docs/meta/coverage.md) | Engine RE pin |

## Changelog

- **2026-10-24:** V3.3.0 (b18) retarget pin: build id, depot manifest, both DLL hashes, save record versions, hook re-check; live b18 soak open.
- **2026-08-28:** V3.2.0 (b9) retarget pin; stale marker/backup refresh note.
- **2026-07-19:** Ownership header; expand re-apply note; related docs.
