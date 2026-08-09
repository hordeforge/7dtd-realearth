# Target game version

**Owns:** pinned game build and install paths for this machine.  
**Not:** install how-to ([MODLET](MODLET.md), [PROTON_INSTALL](PROTON_INSTALL.md)), product status ([MODIFICATIONS](MODIFICATIONS.md)).  
**Hub:** [INDEX](INDEX.md).

| Field | Value |
|---|---|
| **This machine after Steam update** | **V 3.1.0 (b14)** Henpocalypse (Constants Minor=10 Build=14; Steam 2026-08-02) |
| **Client path** | `/home/maci/.local/share/Steam/steamapps/common/7 Days To Die` |
| **Dedicated server** | `…/7 Days to Die Dedicated Server` |
| **Proton userdata** | `…/compatdata/251570/pfx/…/AppData/Roaming/7DaysToDie` |
| **Markers** | `Localization.csv` (3.x), newer `Assembly-CSharp.dll` |

## After every Steam update

```bash
export SEVENDTD_GAME_DIR="/home/maci/.local/share/Steam/steamapps/common/7 Days To Die"
./scripts/install_proton.sh
```

That rebuilds `RealEarth.dll` against the new Managed assemblies and reinstalls:

- `Mods/RealEarth/` (client + dedicated)
- `GeneratedWorlds/RealEarth` under **Proton** Roaming (and native for server tests)

Also re-apply expand if product height is required: `make engine-expand` (Steam Verify restores stock YDim=256).

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
- Generic engine RE pin: [`../../7dtd-research/docs/coverage.md`](../../7dtd-research/docs/coverage.md).

## Height expand state (this machine)

Live client and dedicated `Assembly-CSharp` may already have RealEarth YDim expand applied (`ChunkBlockYDim=16384`). Stock backups live next to the DLL as `Assembly-CSharp.dll.re_stock_bak` (`YDim=256`).

Probe with `realearth engine-audit` or regenerate dumps via `DumpTerrain` (see workspace [`7dtd-research/docs/terrain-height.md`](../../7dtd-research/docs/terrain-height.md)). After Steam Verify, re-run `make engine-expand`.

## Related docs

| Doc | Role |
|---|---|
| [PROTON_INSTALL](PROTON_INSTALL.md) | Proton paths |
| [MODLET](MODLET.md) | Install + expand |
| [HEIGHT_LIMITS](HEIGHT_LIMITS.md) | Expand policy |
| [research coverage](../../7dtd-research/docs/coverage.md) | Engine RE pin |

## Changelog

- **2026-07-19:** Ownership header; expand re-apply note; related docs.
