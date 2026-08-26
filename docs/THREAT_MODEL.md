# RealEarth threat model

**Owns:** attack-surface model: entry points, trust boundaries, assets, threats per boundary, mitigations present vs missing.
**Not:** individual vulnerability fixes (sec-review owns those), CVE inventory, PII compliance mapping.
**Hub:** [`INDEX.md`](INDEX.md). Robustness failure catalog: [`realearth-review.md`](realearth-review.md).

Last reviewed: 2026-08-26 · against commit `0c1f30a`.
Maintain by re-verifying every file reference below after surface changes; delete rows that no longer match code.

---

## 1. Risk-ranked summary

| Rank | ID | Threat | Boundary | Where | Mitigation today |
|---|---|---|---|---|---|
| 1 | T1 | Poisoned third-party pack shapes gameplay/POIs on community servers; distribution unsigned | B3 pack author → operator/game | decode `Source/RealEarth/RteTile.cs:48-134`; settlements `tools/realearth/settlements.py:242-245` (C# ingestion: `CityMapLabels.cs:575-586`) | Format/bounds validation only (`RteTile.cs:40,69-70,163-196`) |
| 2 | T2 | Compromised or hostile https CDN swaps tile bytes; tampered terrain persists to disk cache and is inherited by later sessions | B1 remote tiles | URL build `CdnTilePolicy.cs:13-34`; persist `TileStreamer.cs:576`, `AtomicPublish.cs` | Transport is https-only with redirect-downgrade rejection (`CdnTilePolicy.cs:23`; `TileStreamer.cs:460-465`) but no signature or content hash |
| 3 | T3 | Operator binds `realearth serve` past loopback: packs served unauthenticated | B4 viewer server | `tools/realearth/cli.py:784-820`; server `tools/realearth/viewer_server.py:146-161` | Defaults to 127.0.0.1 + loud warning on any other bind (`cli.py:803-807`); static-only with containment and CSP (`viewer_server.py:63-77,102-113`) |
| 4 | T4 | Build chain compromise or post-patch DLL drift silently runs expanded code nobody verified | B6 build → runtime | `tools/engine_patcher/Program.cs:241-289`; `scripts/apply_engine_expand.sh` | Backup + marker + dry-run + restore; expand records sha256 and `make engine-verify` detects drift (`Program.cs:294-360`; `Makefile:253-255`), but verification is opt-in |
| 5 | T5 | Malicious/corrupt tile causes decode/inflate cost spikes inside the server process | B1/B3 tiles → game process | inflate `RteTile.cs:171-196`; fetch `TileStreamer.cs:458-485` | Bounded: 64 MB fetch cap + body deadline (`TileStreamer.cs:41,60,467-485`); inflate capped to expected size with capacity reserved up front (`RteTile.cs:182-189`); residual is CPU, not memory exhaustion |
| 6 | T8 | Viewer loads three.js from cdn.jsdelivr.net at runtime; whoever controls that origin runs script in the viewer origin (no subresource integrity on importmap modules) | B4 browser ↔ viewer/CDN | importmap `viewer/index.html:12-17`; CSP allows the origin (`viewer_server.py:73`) | Version-pinned URL (`three@0.170.0`) only; https transport; version mirrored by lint/type pins (`scripts/toolchain-versions.env:35-36`) |
| 7 | T6 | Operator clones template and re-enables telnet on an exposed host | B7 deployment | `scripts/serverconfig_height_test.xml:42-45` (`TelnetEnabled=false`, `TelnetPassword` empty) | Template ships telnet off with empty password; re-enable comment demands a strong one |
| 8 | T7 | Viewer XSS regression: pack-controlled settlement strings reaching an HTML sink | B4 browser ↔ viewer | render path `viewer/src/app.ts:146,189,252`; `webmod/src/map-page.ts:61,67` | No HTML sink today: all strings go through `textContent`/`replaceChildren`; pack metadata cannot steer fetches out of the served tree (`viewer/src/pack.ts:19-34`; `webmod/src/pack.ts:17-32`); CSP on the served origin (`viewer_server.py:63-77`) |

Fixes belong to sec-review passes; this file records location and impact only.

## 2. Assets

- **Dedicated-server process integrity/availability.** Mod runs in-process (Harmony) in client and dedicated host (`Source/RealEarth/ModApi.cs:21`); any decode/fetch bug carries game-process authority.
- **World saves.** Terrain inject mutates chunks/saves (`Source/RealEarth/ChunkTerrainInject.cs`); poisoned/corrupt tiles corrupt persistent worlds.
- **Game install directories.** Tile cache writes (`TileStreamer.cs:447-448`), baked worlds under `GeneratedWorlds`, IL-patched DLL.
- **Pipeline durable state.** Baked worlds/packs (`worlds/`, `data/samples/`), the Terrarium source-tile cache (`data/cache/terrarium`, only hedge against upstream dataset loss), and backup archives (`scripts/backup_artifacts.sh:3-8`); all git-ignored and unrebuildable without network.
- **Terrain data fidelity = gameplay fairness.** Elevation/population decide traversal, spawn, city density; a hostile pack is a cheat/griefing primitive.
- **Project reputation.** Operators install mods/packs trusting provenance; nothing here signs artifacts.
- **Not held:** user PII, payment data, signing keys, stored credentials (repo scan finds no secret-shaped artifacts; the test telnet config ships disabled with an empty password, `scripts/serverconfig_height_test.xml:42-45`).

## 3. Entry points (from code)

| # | Entry point | Untrusted input | File |
|---|---|---|---|
| E1 | CDN tile download at runtime (when configured) | HTTP response bytes decoded as RTE1, written to disk. https enforced twice (URL build + fetch, redirect downgrade rejected), size capped at headers and during streamed read | `TileStreamer.cs:346-358,458-485`; `CdnTilePolicy.cs:13-47` |
| E2 | Local `.rte` pack load (`Data/tiles`) | Binary format, length-prefixed zlib sections, embedded POI JSON string (decoded, unused by consumers) | `RteTile.cs:42-134` |
| E3 | Mod config JSON at init | Operator values incl. `TileCdnBaseUrl`, debug flags; validated at startup with logged warnings | `ModApi.cs:21`; `RealEarthConfig.cs:171-290` |
| E4 | Game console commands (`reheight`,`rereveal`,`recities`,`reinject`,`resession`) | Admin-only via console/telnet (game-owned auth); map reveal additionally config-gated | `Source/RealEarth/ConsoleCmdRe*.cs`; `MapReveal.cs:39` |
| E5 | Web dashboard integration (stock webserver serves `webmod/build`) | Runs inside the game webserver's authenticated admin session; calls `/api/serverstats`; persists pack preference in admin localStorage; pack paths validated before fetch | `webmod/src/index.ts:5`; `overview.ts:13`; `settings-store.ts:14,46`; `pack.ts:17-32` |
| E6 | Pipeline CLI (`demo`,`region`,`bake-world`,`export-viewer`,`inspect-tile`,`serve`) | GeoJSON files, GeoTIFFs, CLI args, remote API responses; echoed pack strings sanitized; world names joined onto paths are component-checked | `tools/realearth/cli.py:35-57` |
| E7 | Third-party fetches in pipeline | open-meteo elevation API and AWS terrarium PNG tiles (retry-bounded GETs); fetched tiles persist to a disk cache (`RE_TERRARIUM_CACHE`, default `data/cache/terrarium`) that later builds trust without revalidation; failed publishes unlink their temp file instead of accumulating (`elevation.py:181`) | `tools/realearth/elevation.py:23-51,79,148,151-181,262-266`; `Makefile:59` |
| E8 | Static viewer server + browser app | Same-origin JSON/PNG; user-supplied local JSON file; optional same-origin `data/player.json` position feed (coerced/range-checked, absence tolerated); **remote script origin**: importmap loads three.js from cdn.jsdelivr.net. Server: translated-path containment, directory listings off, security headers, control chars stripped from logs | `cli.py:784-820`; `viewer_server.py:48-56,63-77,79-83,102-113`; `viewer/src/app.ts:80,293,525-528`; `viewer/index.html:12-17` |
| E9 | Install/expand scripts + IL patcher (+ offline `network_protocol_inspector` dumper) | Writes into Steam dirs; patches game DLL; restore extracts operator-supplied tar archives into the repo. Install roots resolve through env overrides (`SEVENDTD_GAME_DIR`/`SEVENDTD_SERVER_DIR`) via `tools/realearth/proton_paths.py`. Lint/build tool pins centralized in one sourced env file (anti-slop tarball by commit SHA, packages by version); CI pins Actions by commit SHA, gates release tags against shipped version, and re-runs the backup/restore drill | `scripts/install_proton.sh:6-7,24-31,75,174`; `engine_patcher/Program.cs:193-232`; `network_protocol_inspector/Program.cs:3`; `scripts/toolchain-versions.env:20-39`; `.github/workflows/release.yml:22-47`; `.github/workflows/ci.yml` (`make artifacts-drill`) |

E5 is easy to miss: whenever an operator opens the control-panel port, our bundle is network-reachable content (auth is the game's, behavior is ours).

## 4. Trust boundaries and flows

- **B1 Remote tile CDN → game process.** Crosses on every miss when `TileCdnBaseUrl` set (`RealEarthConfig.cs:44`). Validation points: https-only URL policy (`CdnTilePolicy.cs:13-34`), fetch-time scheme re-check + redirect downgrade rejection (`TileStreamer.cs:460-465`), magic-byte gate before caching (`TileStreamer.cs:415-421,569-574`), bounded decode (`RteTile.cs:40-196`). Content authenticity remains unnamed territory (T2).
- **B2 Third-party APIs → pipeline workstation → durable cache.** open-meteo/S3 responses decoded offline (`elevation.py`). No validation beyond PNG/library decode, and fetched Terrarium tiles persist to `data/cache/terrarium` (`elevation.py:151-181`) where later builds serve them back without any re-check (`elevation.py:258-263`): a poisoned or silently corrupted cache becomes world truth on every future rebuild (extends T2's persistence half to the pipeline). Deps pinned by `tools/uv.lock`.
- **B3 Pack author → operator → game/pipeline/viewer.** `.rte`, `earth.manifest.json`, `settlements.json`, GeoTIFFs. No signatures; manifest notes are free text. Downstream echo surfaces sanitize (CLI `_display_text` `cli.py:35-43`; viewer server logs `viewer_server.py:48-56`); path-joining of pack names rejects traversal components (`cli.py:45-57`); C# ingestion normalizes names to NFC and strips C0/C1 control chars before they reach log lines (`CityMapLabels.cs:51-74`, applied at `:580`), and saturates out-of-range populations (`CityMapLabels.cs:759-771`).
- **B4 Browser ↔ viewer/webmod (+ CDN script origin).** Viewer origin renders pack strings through text-only DOM APIs; served responses carry CSP/nosniff/frame-deny (`viewer_server.py:63-77`) with listings blocked by an override (`viewer_server.py:79-83`); translated paths must stay inside the served tree (`viewer_server.py:102-113`). The CSP also whitelists `https://cdn.jsdelivr.net` for scripts (`viewer_server.py:73`) because the importmap pulls three.js from there at runtime (`viewer/index.html:16-17`): a third-party script origin inside the viewer trust boundary (T8). WebMod executes within the game's authenticated dashboard session (game owns that boundary); its pack/file fields pass the same path guard as the viewer (`webmod/src/pack.ts:17-32,70,108,229`).
- **B5 Operator ↔ install tooling / backup tooling.** Scripts remove guarded destinations inside Steam dirs (`install_proton.sh:75,174`); gated by explicit `GAME_DIR` existence checks (`install_proton.sh:24-31`; roots resolved via `SEVENDTD_GAME_DIR`/`SEVENDTD_SERVER_DIR`, `install_proton.sh:6-7`, `tools/realearth/proton_paths.py`; Makefile setup). Config and serverconfig writing runs as `realearth.mod_config` / `realearth.server_config` with values passed as argv, so an env-supplied world name or userdata path is data, never Python or XML source; the previous heredocs interpolated them into a script body. The height-test harness moves old saves into a 7-day trash window instead of deleting them (`run_dedicated_height_test.sh:160-175`). Artifact restore verifies sha256/gzip and refuses to clobber existing dirs unless `RE_FORCE_RESTORE=1`, but otherwise trusts the archive it is pointed at (`backup_artifacts.sh:96-125`); the roundtrip including those guardrails is proven on synthetic state by `make artifacts-drill` (`scripts/artifacts_drill.sh`, sandbox via `RE_ROOT`, CI-enforced). Operator trust assumed; not sandboxed.
- **B6 Build → runtime.** Patcher rewrites the managed game DLL; output gains full game-process authority. Marker + stock backup + late-backup convergence exist (`Program.cs:193-232`); the written bytes' sha256 is recorded in the marker (`Program.cs:294-310`) and `--verify` compares current bytes against it (`Program.cs:326-360`, Makefile `engine-verify:253-255`). Release workflow rejects a tag that disagrees with `ModInfo.xml` (`.github/workflows/release.yml:22-47`) and pins Actions by commit SHA. Lint/build tooling is pinned in one sourced file: anti-slop tarball by commit SHA (`toolchain-versions.env:31`), all npm packages by version (`toolchain-versions.env:20-39`), consumed by every build/lint script; three.js viewer pin is mirrored by type/lint gates (`toolchain-versions.env:32-36`).
- **B7 Secrets → code.** No credentials stored or rotated here. Telnet ships disabled with an empty password (`scripts/serverconfig_height_test.xml:42-45`); CDN URL is configuration, not a secret.

Privilege transitions: pipeline shell → game install files (B5); mod tooling → game DLL bytes (B6); tile bytes → in-process decoder running with server privileges (B1/B3 → E1/E2).

## 5. Threats per boundary (STRIDE)

- **B1:** Tampering/Spoofing: a hijacked https CDN or TLS-breaking MITM swaps `.rte`; poison persists via cache (T2). DoS: response sizes and inflate output are capped (`TileStreamer.cs:467-485`; `RteTile.cs:182-189`); refetch churn bounded by the negative cache with a prune threshold (`TileStreamer.cs:36,54,519-553`) and in-flight dedup (`TileStreamer.cs:29,493`). Disclosure: none expected (public Earth data).
- **B2:** Tampering: hostile upstream elevation/population silently becomes world truth; no cross-source check. Persistence half: poisoned Terrarium tiles land in `data/cache/terrarium` and outlive the hostile run (`elevation.py:165-181`). DoS: large PNG decode on a workstation; low impact offline.
- **B3:** Elevation of trust: untrusted pack gets full terrain+POI authority once installed (T1). Repudiation: `sources_note` proves nothing.
- **B4:** Tampering/XSS: currently no HTML sink in either app (T7 is a regression-watch row). Spoofing/script supply chain: the viewer origin trusts cdn.jsdelivr.net for its 3D engine at runtime (T8); WebMod runs with admin-session authority, its fetch targets are path-guarded (`webmod/src/pack.ts:17-32`). DoS: `ThreadingHTTPServer` spawns a thread per connection with no rate limit (`viewer_server.py:151`); loopback-by-default keeps this local.
- **B5:** Data loss: wrong env var redirects destructive paths; mitigated by existence checks and the saves trash window, not dry-run defaults. Restore pointed at a hostile archive writes wherever its members name (operator-supplied input assumed benign); the drill proves the guards work on synthetic state but cannot vouch for a hostile archive's contents.
- **B6:** Persistent code injection via patched DLL (T4); drift verify closes the silent-drift half when run. Toolchain pins centralized in `toolchain-versions.env` (anti-slop tarball by commit SHA at `:31`; packages by version) and CI Actions pinned by commit SHA are the right pattern extended to the build lane; tiles/packs still lack an equivalent.
- **E4 telnet/console:** Elevation via password guessing is game-owned control; the template no longer contributes a weak value (telnet ships disabled; T6 residual is operator re-enable).

DoS summary: the dedicated hot path is now bounded end to end (fetch cap → header gate → inflate cap → dims/section-length checks); what remains is CPU cost per hostile tile and unthrottled connections on the dev viewer server.

## 6. Mitigations map (what exists)

| Control | Covers | File |
|---|---|---|
| https-only CDN URL policy (userinfo/CRLF/control-char/host checks) | T2 transport half | `CdnTilePolicy.cs:13-34` |
| Fetch-time scheme re-check + http redirect downgrade rejection | T2 transport half | `TileStreamer.cs:460-465` |
| Response size cap (declared length + streamed count) and body-read deadline | T5 | `TileStreamer.cs:41,60,467-485` |
| Decoder allocation bounds: magic, version fail-closed, dims ≤ 4096², section lengths, inflate capped to expected size with capacity reserved up front | T5, malformed packs raise instead of corrupting | `RteTile.cs:31-40,52-55,63-64,160-167,171-196` |
| Magic-byte gate before caching/decoding CDN payloads | poisoned-cache blast radius | `TileStreamer.cs:415-421,569-574` |
| Negative-result cache (10 s) with prune threshold + focus heartbeat TTL sweep | refetch hammering, stale-focus leak | `TileStreamer.cs:36,49,54,179-195,519-553` |
| Atomic temp+Replace publish | torn cache files | `AtomicPublish.cs`; called from `TileStreamer.cs:447-448` |
| Fail-closed missing-tile policy (default on) | invented terrain | `RealEarthConfig.cs:90`; `CdnTilePolicy.cs:13-19` |
| Config validation at init with logged warnings | bad operator input | `RealEarthConfig.cs:171-290` |
| Viewer server: path containment, listings off, CSP/nosniff/frame-deny/referrer-policy, log sanitization | T3, T7 support | `viewer_server.py:48-56,63-77,79-83,102-113` |
| Text-only DOM rendering in viewer and webmod; `isSafePackPath` on pack/layer/elev fields in both | T7, metadata-steered fetches | `viewer/src/app.ts:146,189,252`; `viewer/src/pack.ts:19-34,64,99`; `webmod/src/pack.ts:17-32,70,108` |
| Echo sanitization for pack-controlled strings on every consumer: CLI `_display_text`, viewer-server logs, C# `NormalizePlaceName` (NFC + control-char strip) before game-log lines | terminal/log injection, path escape | `cli.py:35-57`; `viewer_server.py:48-56`; `CityMapLabels.cs:51-74,580` |
| Engine patch: backup/marker/dry-run/restore + sha256 recorded at expand + `engine-verify` drift check | T4 | `Program.cs:193-232,294-360`; `Makefile:253-255` |
| `GAME_DIR` existence checks before install/destructive rm; roots resolved via `SEVENDTD_GAME_DIR`/`SEVENDTD_SERVER_DIR` | wrong-target destruction | `Makefile` setup; `install_proton.sh:6-7,24-31`; `tools/realearth/proton_paths.py` |
| Artifact backup/restore: gzip + sha256 verification before declare/restore; restore refuses existing dirs unless forced (moves aside); harness saves go to a dated trash window; roundtrip incl. guardrails proven by CI-run drill on synthetic state | B5 durability/destructive-path threats | `backup_artifacts.sh:63-71,96-125`; `run_dedicated_height_test.sh:160-175`; `scripts/artifacts_drill.sh` |
| Config/serverconfig written by argv-driven Python modules, never shell heredocs; property inserts fail loud instead of silently skipping | script-body injection via env values; a drifting template silently dropping `EACEnabled`/`ServerVisibility` | `realearth/mod_config.py`; `realearth/server_config.py`; `tests/test_config_contract.py` |
| Dependency pinning (`uv.lock`, committed NuGet lock files), centralized lint/build pins (anti-slop tarball by commit SHA; npm packages by version), SHA-pinned CI Actions, release-tag/version gate | B2/B6 supply chain | `tools/uv.lock`; `scripts/toolchain-versions.env:20-39`; `.github/workflows/release.yml:22-47` |

### Gaps (ranked; fixes go to sec-review)

1. No authenticity check for tiles/packs anywhere in the chain: no signature, no hash pinning; runtime CDN fetch, installed packs, *and* the pipeline's Terrarium disk cache (`elevation.py:151-181`) all trust bytes on transport alone, so transport hardening does not help against the CDN itself or a malicious pack publisher (T1, T2).
2. Engine drift verification is opt-in: nothing schedules `make engine-verify` after Steam updates or mod reinstalls, so T4's silent-drift half persists until someone runs it.
3. `realearth serve --bind` past loopback serves everything under the viewer root unauthenticated by design; the warning (`cli.py:803-807`) is the only control (T3).
4. Residual decode cost: a hostile CDN can still spend server CPU on up-to-64 MB payloads per in-flight tile; fan-out is bounded by radius, negative cache, and in-flight dedup but not rate-limited (T5).
5. Viewer script origin: cdn.jsdelivr.net is whitelisted in CSP and pinned by URL only, with no subresource integrity for the importmap modules (T8).
6. No structured security events; failures go to game log via `ModApi.Log` (`ModApi.cs:138`). Note only; o11y-review owns log structure.

Single points of failure: `RteTile.Decode` is the sole gate for local and CDN bytes (hardening it covers E1+E2 at once), and `CdnTilePolicy.TileUrl` is the sole gate for outbound tile URLs.

Documented-but-not-implemented check: no security-relevant claim in `README.md`, [`MODLET.md`](MODLET.md) (config-validation claim at `MODLET.md:69` matches `RealEarthConfig.Validate()` at `RealEarthConfig.cs:171-290`), [`../SECURITY.md`](../SECURITY.md), or [`BACKUP_RESTORE.md`](BACKUP_RESTORE.md) contradicts the code; the DR doc's checksum/refuse-overwrite claims match `backup_artifacts.sh:63-71,96-125` and its restore-drill claim is implemented (`scripts/artifacts_drill.sh`, CI-enforced). Nothing to retract this pass.

## 7. Abuse cases

- **Pack poisoning.** A publisher ships a "free full-Earth" pack with altered heights/population; operators install it; players get unfair geometry/loot. Path: E2 accepts any well-formed RTE1 (`RteTile.cs:48`), gap 1.
- **CDN-borne terrain rewrite.** Whoever controls or compromises the configured https CDN rewrites tiles; they pass the magic gate and land in the disk cache, poisoning later sessions even after the CDN is fixed. Path: `TileStreamer.cs:569-576`, gap 1.
- **Pipeline-cache poisoning.** A compromised workstation or hostile mirror serves Terrarium PNGs once; they are stored to `data/cache/terrarium` and every future rebuild trusts them (`elevation.py:258-263`), silently baking altered elevation into new packs. Same class as the previous case, offline half of gap 1.
- **Viewer-borne script execution (regression watch).** A shared viewer pack embeds markup in a settlement name; operator previews via `realearth serve`. Today nothing renders it as HTML (`showTip` builds text nodes, `viewer/src/app.ts:243-264`), so this is the scenario to re-test if an HTML sink ever appears. Recorded as scenario, not demonstrated.
- **Viewer engine swap.** Whoever controls cdn.jsdelivr.net serves a modified three.module.js; it executes in the viewer origin with same-origin access to pack data and player.json (T8). Version pin without integrity means a changed file at the same URL loads silently.
- **Authenticated-player resource churn.** Position spam creates focus churn; each new area triggers bounded CDN/disk loads. Path: `WorldSession.cs:283` (focus register) → `TileStreamer.UpdateFromAbsolute` (`TileStreamer.cs:108-141`); bounds: `StreamRadiusTiles`/`UnloadRadiusTiles` (`RealEarthConfig.cs:24-25`), miss cache + prune (`TileStreamer.cs:519-553`), in-flight dedup, stale-focus TTL (`TileStreamer.cs:49,179-195`). Amplification against the configured CDN host is capped today.
- **Client-side enforcement:** none relied on; reveal/debug helpers are config-gated server-side (`MapReveal.cs:39`, `DebugRevealFullMap` default false `RealEarthConfig.cs:59`).

## 8. Response readiness (note only)

- Reporting channel documented ([`../SECURITY.md`](../SECURITY.md)); no documented path from "vulnerability reported" to "fix shipped" beyond it.
- Audit trail after an incident is thin: game log lines only (`ModApi.cs:138`). o11y-review owns log structure; sec-review should treat gaps 1-6 above as its aiming list. Durability of evidence itself is covered by [`BACKUP_RESTORE.md`](BACKUP_RESTORE.md) (artifact archives), not by any log retention policy.
