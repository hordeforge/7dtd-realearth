# RealEarth threat model

**Owns:** attack-surface model: entry points, trust boundaries, assets, threats per boundary, mitigations present vs missing.
**Not:** individual vulnerability fixes (sec-review owns those), CVE inventory, PII compliance mapping.
**Hub:** [`INDEX.md`](INDEX.md). Robustness failure catalog: [`realearth-review.md`](realearth-review.md).

Last reviewed: 2026-08-23 · against commit `72c1e24`.
Maintain by re-verifying every file reference below after surface changes; delete rows that no longer match code.

---

## 1. Risk-ranked summary

| Rank | ID | Threat | Boundary | Where | Mitigation today |
|---|---|---|---|---|---|
| 1 | T1 | Malicious/corrupt tile → unbounded inflate/allocation inside the server process (DoS) | B1/B3 tiles → game process | `Source/RealEarth/RteTile.cs:53-79`, inflate `RteTile.cs:122-133`; CDN fetch `Source/RealEarth/TileStreamer.cs:301,420` | Magic-byte gate only (`TileStreamer.cs:302-305`); no size cap |
| 2 | T2 | Unsigned tile CDN over plain-HTTP base URL: tampered terrain persists to disk cache, inherited by later sessions | B1 remote tiles | URL build `Source/RealEarth/CdnTilePolicy.cs:20-29`; config `RealEarthConfig.cs` (`TileCdnBaseUrl`); persist `TileStreamer.cs:332-365` | None (no signature/hash anywhere) |
| 3 | T3 | Poisoned third-party pack shapes gameplay/POIs on community servers; distribution unsigned | B3 pack author → operator/game | decode `RteTile.cs:34-100`; settlements `tools/realearth/cli.py:107-108` | Format validation only (`RteTile.cs:39-57`) |
| 4 | T4 | Viewer XSS: pack-controlled settlement strings rendered via innerHTML | B4 browser ↔ viewer | `viewer/js/app.js:281` (also `:90,:142`); local-JSON input `app.js:316` | None (raw innerHTML) |
| 5 | T5 | Engine expand rewrites game `Assembly-CSharp.dll`; compromised build chain persists code into installs | B6 build → runtime | `tools/engine_patcher/Program.cs:109-168`; `scripts/apply_engine_expand.sh` | Backup + marker + dry-run + restore; no post-patch hash check |
| 6 | T6 | Weak shipped telnet credential template cloned onto real servers | B7 deployment | `scripts/serverconfig_height_test.xml:43` (`TelnetPassword=retest`) | None |
| 7 | T7 | `realearth serve` bound past loopback serves packs unauthenticated with listing | B4 viewer server | `tools/realearth/cli.py:617-663` | Defaults to 127.0.0.1 |

Fixes belong to sec-review passes; this file records location and impact only.

## 2. Assets

- **Dedicated-server process integrity/availability.** Mod runs in-process (Harmony) in client and dedicated host (`Source/RealEarth/ModApi.cs:11-18`); any decode/fetch bug carries game-process authority.
- **World saves.** Terrain inject mutates chunks/saves (`Source/RealEarth/ChunkTerrainInject.cs`); poisoned/corrupt tiles corrupt persistent worlds.
- **Game install directories.** Tile cache writes (`TileStreamer.cs:332-365`), baked worlds under `GeneratedWorlds`, IL-patched DLL.
- **Terrain data fidelity = gameplay fairness.** Elevation/population decide traversal, spawn, city density; a hostile pack is a cheat/griefing primitive.
- **Project reputation.** Operators install mods/packs trusting provenance; nothing here signs artifacts.
- **Not held:** user PII, payment data, signing keys, stored credentials (repo scan finds only the test telnet password above).

## 3. Entry points (from code)

| # | Entry point | Untrusted input | File |
|---|---|---|---|
| E1 | CDN tile download at runtime (when configured) | HTTP response bytes decoded as RTE1, written to disk | `TileStreamer.cs:233-247,295-329,407-443`; `CdnTilePolicy.cs:20-29` |
| E2 | Local `.rte` pack load (`Data/tiles`) | Binary format, length-prefixed zlib sections, embedded POI JSON string (currently decoded, unused by consumers) | `RteTile.cs:28-100` |
| E3 | Mod config JSON at init | Operator values incl. `TileCdnBaseUrl`, debug flags | `ModApi.InitMod`; `RealEarthConfig.cs` |
| E4 | Game console commands (`reheight`,`rereveal`,`recities`,`reinject`,`resession`) | Admin-only via console/telnet (game-owned auth) | `Source/RealEarth/ConsoleCmdRe*.cs` |
| E5 | Web dashboard integration (stock webserver serves `WebMod/bundle.js`) | Runs inside the game webserver's authenticated admin session; calls `/api/serverstats`; loads pack URLs from admin localStorage | `webmod/src/index.ts`; `overview.ts:13`; `settings-store.ts:14,42`; `pack.ts:135,162` |
| E6 | Pipeline CLI (`demo`,`region`,`bake-world`,`export-viewer`,`serve`) | GeoJSON files, GeoTIFFs, CLI args, remote API responses | `tools/realearth/cli.py:19` |
| E7 | Third-party fetches in pipeline | open-meteo elevation API, AWS terrarium PNG tiles | `tools/realearth/elevation.py:43,112,175` |
| E8 | Static viewer server + browser app | Same-origin JSON/PNG; user-supplied local JSON file | `cli.py:617-663`; `viewer/js/app.js:128,153,316,342` |
| E9 | Install/expand scripts + IL patcher | Writes into Steam dirs; patches game DLL; lint gates fetch SHA-pinned GitHub tarballs | `scripts/install_proton.sh`, `scripts/install_height_pack.sh`; `engine_patcher/Program.cs`; `scripts/lint-webmod.sh:47`, `lint-viewer.sh:30` |

E5 is easy to miss: whenever an operator opens the control-panel port, our bundle is network-reachable content (auth is the game's, behavior is ours).

## 4. Trust boundaries and flows

- **B1 Remote tile CDN → game process.** Crosses on every miss when `TileCdnBaseUrl` set. Validation point: magic-byte check only (`TileStreamer.cs:301-310`). Scheme is whatever config says; http accepted.
- **B2 Third-party APIs → pipeline workstation.** open-meteo/S3 responses decoded offline (`elevation.py`). No validation beyond library decode; deps pinned by `tools/uv.lock`.
- **B3 Pack author → operator → game/pipeline/viewer.** `.rte`, `earth.manifest.json`, `settlements.json`, GeoTIFFs. No signatures; manifest notes are free text.
- **B4 Browser ↔ viewer/webmod.** Viewer origin renders pack strings; WebMod executes within the game's authenticated dashboard session (game owns that boundary).
- **B5 Operator ↔ install tooling.** Scripts remove guarded destinations inside Steam dirs (`scripts/install_proton.sh:64,186`); gated by explicit `GAME_DIR` checks (Makefile setup). Operator trust assumed; not sandboxed.
- **B6 Build → runtime.** Patcher rewrites the managed game DLL; output gains full game-process authority. Marker+backup exist (`Program.cs:155-168`); written bytes are not hash-verified.
- **B7 Secrets → code.** No credentials stored or rotated here. Only secret-shaped artifact: test telnet password (`serverconfig_height_test.xml:43`). CDN URL is configuration, not a secret.

Privilege transitions: pipeline shell → game install files (B5); mod tooling → game DLL bytes (B6); tile bytes → in-process decoder running with server privileges (B1/B3 → E1/E2).

## 5. Threats per boundary (STRIDE)

- **B1:** Spoofing/Tampering: MITM or hijacked CDN swaps `.rte`; poison persists via cache (T2). DoS: uncapped download + inflate exhausts memory (T1); refetch churn bounded by 10 s negative cache (`TileStreamer.cs:35,399-405`). Disclosure: none expected (public Earth data).
- **B2:** Tampering: hostile upstream elevation/population silently becomes world truth; no cross-source check. DoS: large PNG decode on a workstation; low impact offline.
- **B3:** Elevation of trust: untrusted pack gets full terrain+POI authority once installed (T3). Repudiation: `sources_note` proves nothing.
- **B4:** Tampering/XSS: pack strings reach innerHTML sinks (T4). Spoofing: WebMod runs with admin-session authority; current bundle uses React text rendering (no raw HTML injection found in `webmod/src`), so the live sink is the viewer.
- **B5:** Data loss: wrong env var redirects destructive paths; mitigated by existence checks, not dry-run defaults.
- **B6:** Persistent code injection via patched DLL (T5); lint tarballs pinned by SHA (`lint-webmod.sh:47`) is the right pattern to extend to packs/tiles.
- **E4 telnet/console:** Elevation via password guessing; game-owned control, our contribution is the weak template value (T6).

DoS summary: uncapped network read + decompression on the dedicated hot path is the exposure that matters; player-driven prefetch fan-out is bounded (`StreamRadiusTiles` default 2, negative cache).

## 6. Mitigations map (what exists)

| Control | Covers | File |
|---|---|---|
| Magic-byte gate before caching/decoding CDN payloads | partial T1 | `TileStreamer.cs:302-305,421-428` |
| Header + elevation size validation in decoder | malformed pack raises instead of corrupting | `RteTile.cs:39-43,56-57` |
| 10 s negative-result cache | refetch hammering | `TileStreamer.cs:35,399-405` |
| Atomic temp+Replace publish | torn cache files | `TileStreamer.cs:332-365` |
| Fail-closed missing-tile policy (ocean placeholder + miss log) | invented terrain | `CdnTilePolicy.cs:12-19`; `FailClosedMissingTiles` in `RealEarthConfig.cs` |
| Engine patch backup/marker/dry-run/restore | recoverable T5 | `Program.cs:109-168`; Makefile `engine-expand-dry`,`engine-restore` |
| `GAME_DIR` checks before install | wrong-target destruction | Makefile setup target |
| Dependency pinning (`uv.lock`) + CI gates | B2 supply chain | `tools/uv.lock`; `.github/workflows` |
| React text rendering in webmod | dashboard-side injection | `webmod/src/*` |

### Gaps (ranked; fixes go to sec-review)

1. No size caps on CDN bodies or inflate output; decoder allocates from payload-controlled lengths (`RteTile.cs:53-79`).
2. No authenticity check for tiles/packs: no signature, no hash pinning, http allowed (T2, T3).
3. Viewer innerHTML sinks fed by pack-controlled strings (T4).
4. Weak telnet password shipped as template (T6).
5. No post-patch DLL hash verification after expand (T5 residual).
6. No structured security events; failures go to game log via `ModApi.Log` (`ModApi.cs:139`). Note only; o11y-review owns log structure.

Single point of failure: `RteTile.Decode` is the sole gate for local and CDN input; hardening it covers E1+E2 at once.

Documented-but-not-implemented check: no security doc claims validation/auth/sandboxing for these surfaces, so there is no false mitigation claim to retract this pass.

## 7. Abuse cases

- **Pack poisoning.** A publisher ships a "free full-Earth" pack with altered heights/population; operators install it; players get unfair geometry/loot. Path: E2 accepts any well-formed RTE1 (`RteTile.cs:34`), gap 2.
- **Viewer-borne script execution.** A shared viewer pack embeds markup in a settlement name; operator previews via `realearth serve`; script runs in the viewer origin. Path: `settlements.json` → `viewer/js/app.js:281`. Recorded as scenario, not demonstrated.
- **Authenticated-player resource churn.** Position spam creates focus churn; each new area triggers bounded CDN/disk loads (radius 2 tiles, 10 s miss cache). Path: `WorldSession.cs:268,315` → `TileStreamer.UpdateFromAbsolute` (`TileStreamer.cs:75-90`). Bandwidth amplification against the configured CDN host, capped today.
- **Client-side enforcement:** none relied on; reveal/debug helpers are config-gated (`DebugRevealFullMap` default false, `RealEarthConfig.cs`).

## 8. Response readiness (note only)

- No documented path from "vulnerability reported" to "fix shipped"; [`../../SECURITY.md`](../SECURITY.md) names the reporting channel.
- Audit trail after an incident is thin: game log lines only (`ModApi.Log`). o11y-review owns log structure; sec-review should treat gaps 1-5 above as its aiming list.
