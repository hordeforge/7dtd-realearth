# Target game version

**Owns:** pinned game build and install paths for this machine.  
**Not:** install how-to ([MODLET](MODLET.md), [PROTON_INSTALL](PROTON_INSTALL.md)), product status ([MODIFICATIONS](MODIFICATIONS.md)).  
**Hub:** [INDEX](INDEX.md).

| Field | Value |
|---|---|
| **This machine after Steam update** | **V 3.2.0 (b9)** (dedicated log `Version: V 3.2.0 (b9)`, Compatibility `V 3.2.0`, Build `LinuxServer 64 Bit`; Steam 2026-08-28) |
| **Client path** | `~/.local/share/Steam/steamapps/common/7 Days To Die` |
| **Dedicated server** | `…/7 Days to Die Dedicated Server` |
| **Proton userdata** | `…/compatdata/251570/pfx/…/AppData/Roaming/7DaysToDie` |
| **Markers** | `Localization.csv` (3.x), newer `Assembly-CSharp.dll` |

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

**3.2.0 retarget note (2026-08-28):** the update replaced `Assembly-CSharp.dll` on both
installs. The runtime transpiler binds against the new build (see `BuildGuard`
in [THREAT_MODEL](THREAT_MODEL.md)); rebuild the mod against the new DLL after
each game update (`make build` / `make install`). Live dedicated boot on 3.2.0 (b9)
binds all hooks: heightQ=7 gen=4
chunkIdx=2 playerTick=2 worldReady=1 `injectOk=True productOk=True` (see
`docs/realearth-runtime.md` status).

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
- V3.2.0 exact-diff changelog: [`../../7dtd-engine-research/docs/releases/changelog-3.2.0.md`](../../7dtd-engine-research/docs/releases/changelog-3.2.0.md) (IL-verified; terrain/save/loop unchanged, wire damage/POI packages changed).

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

- **2026-08-28:** V3.2.0 (b9) retarget pin; stale marker/backup refresh note.
- **2026-07-19:** Ownership header; expand re-apply note; related docs.
