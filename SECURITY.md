# Security policy

Project scope: RealEarth, a 7 Days to Die V3.1.0 mod plus its offline data pipeline.
It holds no user PII, credentials, or signing keys.

## Reporting

Report vulnerabilities via GitHub Issues on this repository:
https://github.com/hordeforge/7dtd-realearth/issues

Please include the affected file/entry point; [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md)
lists the known surfaces (tile decoder, CDN fetch path, viewer, install tooling) so reports can be aimed precisely.

## In scope

- `.rte` tile decoding and the runtime CDN fetch path (`Source/RealEarth/RteTile.cs`, `Source/RealEarth/TileStreamer.cs`)
- The web viewer and WebMod bundle (`viewer/js`, `webmod/src`)
- Pipeline CLI input handling (`tools/realearth`)
- Install and engine-expand tooling (`scripts/`, `tools/engine_patcher`)

## Out of scope

- Vulnerabilities in 7 Days to Die itself or its stock webserver/telnet auth (report to The Fun Pimps)
- Compromise of an operator's own machine by someone with local shell access
- Social engineering of upstream data providers

## Supported versions

Only the current `main` branch receives fixes. There are no tagged release branches.

## Known gaps

Ranked open threats live in [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md) section 6;
they are tracked there rather than duplicated here.
