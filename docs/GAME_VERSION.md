# Target game version

**Owns:** pinned game build and install paths for this machine.  
**Not:** install how-to ([MODLET](MODLET.md), [PROTON_INSTALL](PROTON_INSTALL.md)), product status ([MODIFICATIONS](MODIFICATIONS.md)).  
**Hub:** [INDEX](INDEX.md).

| Field | Value |
|---|---|
| **This machine after Steam update** | **V 3.4.0 (b10)** (dedicated log `Version: V 3.4.0 (b10)`, Compatibility `V 3.4.0`, Build `LinuxServer 64 Bit`; Steam 2026-11-05) |
| **VersionInformation** | `(3, 40, 10)` |
| **Stock wire string** | `V3.4.0 b10` |
| **Steam build id** | 26310339 (dedicated); client app 251570 buildid 26309840 |
| **Depot 294422 manifest** | `5022117301453546978` |
| **`Assembly-CSharp.dll` (dedicated)** | sha256 `00a962dbbb5ef1bb454368322221f9eb4148dc2d548ed2b77244f9bda5ecc167`, 11752960 bytes |
| **`Assembly-CSharp.dll` (client)** | sha256 `cb54022ccc862aa673e0ee55dafe67d842b364c80df6916958d171e959656c58`, 11980288 bytes |
| **Client path** | `~/.local/share/Steam/steamapps/common/7 Days To Die` |
| **Dedicated server** | `…/7 Days to Die Dedicated Server` |
| **Proton userdata** | `…/compatdata/251570/pfx/…/AppData/Roaming/7DaysToDie` |
| **Markers** | `Localization.csv` (3.x), newer `Assembly-CSharp.dll` |

Pins are machine-read; the exhaustive release delta lives in
[`../../7dtd-engine-research/docs/releases/changelog-3.4.0.md`](../../7dtd-engine-research/docs/releases/changelog-3.4.0.md)
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

**3.4.0 retarget note (2026-11-05):** the update replaced `Assembly-CSharp.dll`
on both installs. It adds two wire packages (`NetPackageDroneRecoveryRequest`
45, `...Response` 46) and shifts every id above 46 by 2, removes every
server-side dynamic-mesh call site (console init only), flattens carry capacity
to 96 and adds a trader drone-recovery dialog. No save record version moved:
`main.ttw` 23, `.ttp` 62, `EntityCreationData` 38, `TEFeatureStorage` 20,
`Bag` 2 and `Equipment` 6 are the b18 values, so a b18 world loads here and
world compatibility is unchanged. The corpus owns the delta:
[`changelog-3.4.0.md`](../../7dtd-engine-research/docs/releases/changelog-3.4.0.md).

RealEarth's reflection targets were checked against both V3.4.0 assemblies
with `monodis` (2026-11-05): all 30 required targets are present, covering the
height queries, terrain generate, chunk index, player tick and unload, world
ready/save, longitude wrap and the `PrefabInstance` ctor / `CopyIntoWorld` /
`PrefabCache.GetPrefab` prefab path. The engine constants the YDim transpiler
rewrites are unchanged (`ChunkBlockYDim` 256, `ChunkBlockLayers` 64,
`cMaxHeight` 255), so the expand still applies. `BuildGuard` now lists both
V3.4.0 hashes and keeps the b18 rows as reviewed history. **Live re-soak on
V3.4.0 is still open**; what verifies it is step 3 below plus
`[RealEarth] RealEarth init OK` in a client boot.

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
- V3.3.0 exact-diff changelog: [`../../7dtd-engine-research/docs/releases/changelog-3.4.0.md`](../../7dtd-engine-research/docs/releases/changelog-3.4.0.md) (IL-verified; save records bumped, inventory/equipment reworked, `AssetManagement` and `Services.Analytics` added, console registry 188 -> 190).

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

- **2026-11-05:** V3.4.0 (b10) retarget pin: build ids, depot manifest, both DLL hashes, both `BuildGuard` rows, 30 hook targets re-checked on both assemblies, engine constants re-audited; live V3.4.0 soak open.
- **2026-10-24:** V3.3.0 (b18) retarget pin: build id, depot manifest, both DLL hashes, save record versions, hook re-check; live b18 soak open.
- **2026-08-28:** V3.2.0 (b9) retarget pin; stale marker/backup refresh note.
- **2026-07-19:** Ownership header; expand re-apply note; related docs.
