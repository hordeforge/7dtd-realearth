# Terrain-delta persistence rules

**Owns:** what survives tile unload/reload for terrain changes and player
builds, and what the mod explicitly does NOT own. Session origin/absolute
persistence: [MODIFICATIONS.md](MODIFICATIONS.md) + the `SessionStateStore`
tests. Hub: [INDEX.md](INDEX.md).

## 1. The rule in one line

**RealEarth is stateless about terrain deltas.** Player block edits, density
changes, and structural changes are persisted by **vanilla 7DTD chunk/region
saving** (`WorldState.SaveLoad`, region files) exactly as in a stock world.
RealEarth never writes terrain back into `.rte` packs and never serializes
player edits itself.

## 2. Why this is correct

- The game already saves modified chunks (`.7rg`/region files) on
  autosave/save, independent of any mod.
- RealEarth's `TileStreamer` only caches **read-only source tiles** (`.rte`)
  for sampling; eviction (`EvictOutsideAllFoci`, multi-center unload radius)
  drops those cached copies from memory - it never touches the chunk/region
  files or the `.rte` on disk.
- The mod's `WorldSavePostfix` writes only the **session snapshot**
  (origin + absolute XZ + scope) to `Config/realearth.session.json`; it does
  not write block data.
- So unload/reload of a RealEarth tile has zero effect on terrain deltas:
  the game reloads the region file, which includes the player's edits.

## 3. What the mod persists (and where)

| What | Mechanism | Survives |
|---|---|---|
| Player block edits / builds | Vanilla region save | Yes (stock behavior) |
| Origin + absolute position | `SessionStateStore` -> `realearth.session.json` | Yes (restored on load) |
| Land claims (SharedFixed) | Vanilla (block-claim entities in region save) | Yes |
| `.rte` source tiles | Pack files on disk (read-only) | Yes (reloaded from disk) |
| Cached decoded tiles | `TileStreamer._hot` memory cache | No (re-decoded on demand; fine) |

## 4. Edge cases

- **Origin slide + builds:** `WorldSession` refuses to slide when land claims
  exist (`Origin slide refused: land claims present`). Without land claims,
  an origin slide remaps coordinates; builds at absolute positions stay
  consistent with the session snapshot. Absolute-build persistence under
  slide is still the open live item (see TODO).
- **Player leaves / tile evicts:** cached `.rte` tiles outside every focus
  unload radius are dropped; the region file (with the player's edits) stays
  on disk. Rejoining re-samples the source tiles and the game reloads the
  region.
- **Pack updated on disk:** a rebuilt `.rte` pack replaces the source; player
  edits in region files are separate and unaffected (they overlay the new
  terrain on reload).

## 5. Test coverage

- `test_p4_session_snapshot_roundtrip`, `test_p4_session_restore_is_scoped_to_world_save`,
  `test_world_save_session_path`, `test_dedicated_session_absolute_policy`:
  session origin/absolute persistence.
- `test_streamed_e2e` (missing-tile fail-closed, sample contract): source-tile
  behavior on unload/reload.
- The eviction contract (cache drops, disk untouched) is source-pinned in
  `test_phase_cores` (streamer eviction + `EvictOutsideAllFoci`).

## 6. Open (live)

Player-delta persistence under an **origin slide** with builds (beyond land
claims), and multi-player deltas near window/tile boundaries - both need a live
client. Until then the rule above holds: deltas live in region files, never in
RealEarth.
