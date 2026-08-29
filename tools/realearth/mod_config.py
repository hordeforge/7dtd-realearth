#!/usr/bin/env python3
"""Write the installed RealEarth mod config (DEST/Config/realearth.json).

Single source for what the shell install scripts used to embed as inline
python heredocs (start_dedicated_minimal.sh, run_dedicated_height_test.sh,
install_height_pack.sh): load the repo template (multiplayer template first,
then the default), apply KEY=VALUE overrides, optionally sync world dimensions
from the pack manifest, then write. Stdlib only so it runs where uv does not.

Usage:
  PYTHONPATH=tools python3 -m realearth.mod_config write DEST ROOT [--fresh] [KEY=VALUE ...]

KEY=VALUE sets unconditionally; KEY?=VALUE only fills a key the templates did
not provide. Values parse as JSON scalars (true/false/null/int/float), falling
back to raw strings.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from realearth import DEFAULT_LOCAL_WINDOW_SIZE, PLANET_CANVAS_MIN_WIDTH, JsonDict


def parse_scalar(text: str) -> object:
    lowered = text.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "none", ""}:
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


def apply_override(cfg: JsonDict, pair: str) -> None:
    if "?=" in pair:
        key, _, raw = pair.partition("?=")
        if not key:
            raise SystemExit(f"ERROR: override must be KEY=VALUE or KEY?=VALUE, got: {pair!r}")
        cfg.setdefault(key, parse_scalar(raw))
        return
    key, sep, raw = pair.partition("=")
    if not sep or not key:
        raise SystemExit(f"ERROR: override must be KEY=VALUE, got: {pair!r}")
    cfg[key] = parse_scalar(raw)


def sync_manifest_dimensions(
    dest: Path,
    cfg: JsonDict,
    include_bbox: bool = False,
    max_window: int | None = None,
    spawn_from_bbox: bool = False,
) -> bool:
    """Patch world dimensions (optionally bbox) from DEST/Data/tiles/earth.manifest.json."""
    manifest_path = dest / "Data" / "tiles" / "earth.manifest.json"
    if not manifest_path.is_file():
        return False
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cfg["WorldWidth"] = int(manifest.get("world_width") or 512)
    cfg["WorldHeight"] = int(manifest.get("world_height") or 512)
    cfg["TileSize"] = int(manifest.get("tile_size") or 512)
    window = min(cfg["WorldWidth"], cfg["WorldHeight"])
    cfg["LocalWindowSize"] = min(window, max_window) if max_window else window
    # Wrap follows the synced canvas, matching ModApi.TryApplyPackManifest: a
    # regional pack must never wrap at the antimeridian.
    cfg["EnableLongitudeWrap"] = cfg["WorldWidth"] >= PLANET_CANVAS_MIN_WIDTH
    if include_bbox:
        bbox = manifest.get("bbox") or {}
        for key in ("west", "south", "east", "north"):
            if key in bbox:
                cfg[f"Bbox{key.capitalize()}"] = float(bbox[key])
        if spawn_from_bbox and len(bbox) == 4:
            cfg["DefaultSpawnLon"] = (cfg["BboxWest"] + cfg["BboxEast"]) * 0.5
            cfg["DefaultSpawnLat"] = (cfg["BboxSouth"] + cfg["BboxNorth"]) * 0.5
    return True


def apply_height_test_meta(dest: Path, cfg: JsonDict) -> None:
    """Spawn point and engine ceiling from DEST/Data/tiles/height_test.json."""
    meta_path = dest / "Data" / "tiles" / "height_test.json"
    if not meta_path.is_file():
        return
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if meta.get("summit_lon") is not None:
        cfg["SpawnLongitude"] = float(meta["summit_lon"])
        cfg["SpawnLatitude"] = float(meta["summit_lat"])
        cfg["DefaultSpawnLon"] = cfg["SpawnLongitude"]
        cfg["DefaultSpawnLat"] = cfg["SpawnLatitude"]
    # Staged maps may set engine_max_game_y; Everest-scale fixtures historically
    # wrote 11000. The product ceiling is 29000 now, so a fixture value must only
    # RAISE the configured ceiling (monotonic), never downgrade it: the config
    # knob from the caller (e.g. scripts write EngineMaxGameY=29000) wins over
    # a stale fixture hint.
    engine_max = int(meta.get("engine_max_game_y") or 0)
    if engine_max > 500 and engine_max > int(cfg.get("EngineMaxGameY") or 0):
        cfg["EngineMaxGameY"] = engine_max


def build_config(root: Path, fresh: bool, template: Path | None = None) -> JsonDict:
    if fresh:
        return {}
    if template is not None:
        if not template.is_file():
            raise SystemExit(f"ERROR: no config template at {template}")
        return json.loads(template.read_text(encoding="utf-8"))
    for name in ("realearth.mp.json", "realearth.json"):
        candidate = root / "Config" / name
        if candidate.is_file():
            return json.loads(candidate.read_text(encoding="utf-8"))
    return {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p_write = parser.add_subparsers(dest="command", required=True).add_parser(
        "write", help="write DEST/Config/realearth.json"
    )
    p_write.add_argument("dest", type=Path, help="installed mod directory")
    p_write.add_argument("root", type=Path, help="repository root holding Config/ templates")
    p_write.add_argument(
        "--fresh",
        action="store_true",
        help="ignore repo templates and start from an empty config",
    )
    p_write.add_argument(
        "--sync-manifest",
        action="store_true",
        help="override world dimensions from DEST/Data/tiles/earth.manifest.json",
    )
    p_write.add_argument(
        "--sync-bbox",
        action="store_true",
        help="with --sync-manifest, also copy the manifest bbox into Bbox* keys",
    )
    p_write.add_argument(
        "--spawn-from-bbox",
        action="store_true",
        help="with --sync-bbox, default the spawn point to the bbox centre",
    )
    p_write.add_argument(
        "--max-window",
        type=int,
        default=None,
        help=f"cap LocalWindowSize when syncing (install default {DEFAULT_LOCAL_WINDOW_SIZE})",
    )
    p_write.add_argument(
        "--template",
        type=Path,
        default=None,
        help="read this config file instead of scanning ROOT/Config for a template",
    )
    p_write.add_argument(
        "--height-test-meta",
        action="store_true",
        help="apply spawn point and engine ceiling from DEST/Data/tiles/height_test.json",
    )
    p_write.add_argument("overrides", nargs="*", metavar="KEY[?]=VALUE")
    args = parser.parse_args(argv)

    cfg = build_config(args.root, args.fresh, args.template)
    for pair in args.overrides:
        apply_override(cfg, pair)
    if args.sync_manifest:
        synced = sync_manifest_dimensions(
            args.dest,
            cfg,
            include_bbox=args.sync_bbox,
            max_window=args.max_window,
            spawn_from_bbox=args.spawn_from_bbox,
        )
        if not synced:
            print(f"note: no manifest at {args.dest / 'Data' / 'tiles' / 'earth.manifest.json'}")
    if args.height_test_meta:
        apply_height_test_meta(args.dest, cfg)

    out_path = args.dest / "Config" / "realearth.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    summary = " ".join(
        f"{key}={cfg[key]}"
        for key in ("WorldWidth", "WorldHeight", "TileSize", "LocalWindowSize")
        if key in cfg
    )
    print(f"config -> {out_path}  {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
