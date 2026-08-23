"""CLI: realearth <command> ..."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import click

from realearth import DEFAULT_SEA_LEVEL_GAME_Y, __version__
from realearth.coords import EarthGrid, block_to_lonlat, lonlat_to_block
from realearth.region import build_region, world_tile_indices_for_bbox
from realearth.settlements import SEED_SETTLEMENTS, load_settlements_geojson
from realearth.tile_format import read_manifest, read_tile, tile_path


@click.group()
@click.version_option(__version__, prog_name="realearth")
def main() -> None:
    """RealEarth tools: real-world data → 7 Days to Die tiles / heightmaps."""


def _require_finite(name: str, value: float) -> None:
    """Reject NaN/inf coordinates as usage errors instead of crashing later."""
    if not math.isfinite(value):
        raise click.BadParameter(f"must be a finite number, got {value}", param_hint=name)


@main.command("info")
def info_cmd() -> None:
    """Print grid constants and scale facts."""
    g = EarthGrid()
    click.echo(f"RealEarth tools v{__version__}")
    click.echo(f"World size (1:1 blocks): {g.width} x {g.height}")
    click.echo(f"Default tile size: {g.tile_size}")
    click.echo(f"Tiles on full Earth: {g.tiles_x} x {g.tiles_z} = {g.tiles_x * g.tiles_z:,}")
    click.echo("1 block = 1 meter (vanilla 7DTD).")
    click.echo("Stock engine height ~0-255; RealEarth YDim expand enables tall 1:1 columns.")
    click.echo("Longitude wraps; latitude clamps at poles.")


# Numeric positionals may be negative (-74.006); without this Click reads the
# leading dash as an option and every Americas longitude fails.
@main.command("lonlat", context_settings={"ignore_unknown_options": True})
@click.argument("lon", type=float)
@click.argument("lat", type=float)
def lonlat_cmd(lon: float, lat: float) -> None:
    """Convert lon lat → block X Z and tile indices."""
    _require_finite("LON", lon)
    _require_finite("LAT", lat)
    g = EarthGrid()
    x, z = lonlat_to_block(lon, lat, g)
    click.echo(f"block: {x} {z}")
    click.echo(f"tile:  {x // g.tile_size} {z // g.tile_size}")
    lon2, lat2 = block_to_lonlat(x, z, g)
    click.echo(f"roundtrip lon/lat: {lon2:.6f} {lat2:.6f}")


@main.command("build-region")
@click.option("--west", type=float, required=True, help="West longitude")
@click.option("--south", type=float, required=True, help="South latitude")
@click.option("--east", type=float, required=True, help="East longitude")
@click.option("--north", type=float, required=True, help="North latitude")
@click.option("--out", "out_dir", type=click.Path(), required=True, help="Output directory")
@click.option(
    "--source",
    type=click.Choice(["synthetic", "open_meteo", "terrarium", "geotiff"]),
    default="synthetic",
    help="Elevation: synthetic | open_meteo | terrarium (open AWS DEM tiles) | geotiff",
)
@click.option("--resolution", "resolution_m", type=float, default=30.0, show_default=True,
              help="Meters per sample (use 1 for true 1:1, huge)")
@click.option("--tile-size", type=int, default=512, show_default=True)
@click.option("--name", default="RealEarthRegion", show_default=True)
@click.option("--settlements", type=click.Path(exists=True), default=None,
              help="Optional GeoJSON of settlements")
@click.option("--max-dim", type=int, default=2048, show_default=True,
              help="Cap longest side in samples")
@click.option("--geotiff", type=click.Path(exists=True), default=None,
              help="DEM GeoTIFF path when --source geotiff (Copernicus/SRTM)")
@click.option("--population-geotiff", type=click.Path(exists=True), default=None,
              help="People/km² GeoTIFF (WorldPop / GHSL-POP) for real city density")
@click.option("--built-geotiff", type=click.Path(exists=True), default=None,
              help="Built-up fraction GeoTIFF (GHS-BUILT) for building fabric density")
@click.option("--terrarium-zoom", type=int, default=10, show_default=True,
              help="Terrarium tile zoom (8=coarse, 12=detail, more downloads)")
@click.option("--no-export", is_flag=True, help="Skip heightmap/biomes PNG export")
def build_region_cmd(
    west: float,
    south: float,
    east: float,
    north: float,
    out_dir: str,
    source: str,
    resolution_m: float,
    tile_size: int,
    name: str,
    settlements: str | None,
    max_dim: int,
    geotiff: str | None,
    population_geotiff: str | None,
    built_geotiff: str | None,
    terrarium_zoom: int,
    no_export: bool,
) -> None:
    """Build a regional tile pack + optional 7DTD heightmap export.

    For realism without Google: --source terrarium or --source geotiff (Copernicus DEM).
    Google Earth data cannot be bulk-reused; see docs/REALISM_AND_GOOGLE_EARTH.md.
    """
    if east <= west or north <= south:
        raise click.ClickException("bbox must have east>west and north>south")
    settles = list(SEED_SETTLEMENTS)
    if settlements:
        settles = load_settlements_geojson(Path(settlements))
        click.echo(f"Loaded {len(settles)} settlements from GeoJSON")

    click.echo(f"Building region {west},{south} → {east},{north} source={source} ...")
    manifest = build_region(
        west,
        south,
        east,
        north,
        Path(out_dir),
        resolution_m=resolution_m,
        tile_size=tile_size,
        source=source,
        settlements=settles,
        name=name,
        also_export_7dtd=not no_export,
        max_dim=max_dim,
        geotiff=Path(geotiff) if geotiff else None,
        terrarium_zoom=terrarium_zoom,
        population_geotiff=Path(population_geotiff) if population_geotiff else None,
        built_geotiff=Path(built_geotiff) if built_geotiff else None,
    )
    click.echo(f"Wrote {len(manifest.tiles)} tiles → {out_dir}")
    click.echo(f"Samples: {manifest.world_width} x {manifest.world_height}")
    click.echo(f"m/sample: {manifest.meters_per_block}")
    if not no_export:
        click.echo(f"7DTD export: {Path(out_dir) / 'export_7dtd'}")


@main.command("demo")
@click.option("--out", "out_dir", type=click.Path(), default="data/samples/demo_region",
              show_default=True, help="Output directory")
@click.option("--source", type=click.Choice(["synthetic", "open_meteo"]),
              default="synthetic", show_default=True,
              help="Elevation source (synthetic needs no network)")
def demo_cmd(out_dir: str, source: str) -> None:
    """Build a small playable demo region (approx Denver area footprint)."""
    # ~0.5 deg box around Denver (~40-50 km) at 60 m/sample → small pack
    west, south, east, north = -105.3, 39.5, -104.7, 40.0
    click.echo("Demo bbox: Denver-ish foothills")
    manifest = build_region(
        west,
        south,
        east,
        north,
        Path(out_dir),
        resolution_m=60.0,
        source=source,
        name="RealEarth_Demo_Denver",
        max_dim=1024,
    )
    click.echo(f"Done: {out_dir} ({len(manifest.tiles)} tiles)")
    click.echo("Open export_7dtd/preview.png to inspect.")


@main.command("list-tiles")
@click.argument("pack_dir", type=click.Path(exists=True))
def list_tiles_cmd(pack_dir: str) -> None:
    """List tiles in a pack from earth.manifest.json."""
    man_path = Path(pack_dir) / "earth.manifest.json"
    if not man_path.is_file():
        raise click.ClickException(
            f"no earth.manifest.json in {pack_dir} "
            f"(create a pack first: realearth build-region ... --out {pack_dir})"
        )
    m = read_manifest(man_path)
    click.echo(json.dumps(m.to_dict(), indent=2))


@main.command("inspect-tile")
@click.argument("pack_dir", type=click.Path(exists=True))
@click.argument("tx", type=int)
@click.argument("tz", type=int)
def inspect_tile_cmd(pack_dir: str, tx: int, tz: int) -> None:
    """Print stats for one .rte tile."""
    path = tile_path(Path(pack_dir), tx, tz)
    if not path.exists():
        raise click.ClickException(
            f"missing {path} (tiles in this pack: realearth list-tiles {pack_dir})"
        )
    t = read_tile(path)
    elev = t.elevation_m
    click.echo(f"tile ({tx},{tz}) shape={elev.shape}")
    click.echo(
        f"elev m: min={float(elev.min()):.1f} "
        f"max={float(elev.max()):.1f} mean={float(elev.mean()):.1f}"
    )
    if t.landcover is not None:
        import numpy as np

        vals, counts = np.unique(t.landcover, return_counts=True)
        click.echo(
            "landcover counts: "
            + ", ".join(f"{int(v)}:{int(c)}" for v, c in zip(vals, counts, strict=True))
        )
    if t.population is not None:
        click.echo(f"population byte max={int(t.population.max())}")
    if t.poi_blob:
        from realearth.settlements import decode_poi_blob

        pois = decode_poi_blob(t.poi_blob)
        click.echo(f"pois: {len(pois)}")
        for p in pois:
            click.echo(
                f"  - {p.get('name')} ({p.get('band')}) "
                f"@ {p.get('local_x')},{p.get('local_z')}"
            )


@main.command("planet-tiles")
@click.option("--west", type=float, required=True, help="West longitude")
@click.option("--south", type=float, required=True, help="South latitude")
@click.option("--east", type=float, required=True, help="East longitude")
@click.option("--north", type=float, required=True, help="North latitude")
@click.option("--tile-size", type=int, default=512, show_default=True,
              help="Tile edge in blocks")
def planet_tiles_cmd(
    west: float, south: float, east: float, north: float, tile_size: int
) -> None:
    """List absolute Earth tile indices covering a bbox (planning full planet builds)."""
    if east <= west or north <= south:
        raise click.ClickException("bbox must have east>west and north>south")
    tiles = world_tile_indices_for_bbox(west, south, east, north, tile_size=tile_size)
    click.echo(f"{len(tiles)} tiles")
    for tx, tz in tiles[:50]:
        click.echo(f"{tx} {tz}")
    if len(tiles) > 50:
        click.echo(f"... and {len(tiles) - 50} more")


@main.command("wrap-check", context_settings={"ignore_unknown_options": True})
@click.argument("x", type=int)
def wrap_check_cmd(x: int) -> None:
    """Show wrapped X on the full Earth grid (antimeridian)."""
    g = EarthGrid()
    click.echo(f"wrap_x({x}) = {g.wrap_x(x)}")
    lon, _ = block_to_lonlat(g.wrap_x(x), g.height // 2, g)
    click.echo(f"lon at equator row: {lon:.6f}")


@main.command("height-test-map")
@click.option(
    "--repo",
    type=click.Path(exists=True),
    default=None,
    help="Repo root (default: parent of tools/)",
)
@click.option("--size", type=int, default=2048, show_default=True, help="Baked world edge")
@click.option(
    "--source",
    type=click.Choice(["terrarium", "open_meteo", "synthetic"]),
    default="terrarium",
    show_default=True,
    help="DEM: real AWS Terrarium | Open-Meteo | synthetic cone",
)
@click.option("--terrarium-zoom", type=int, default=11, show_default=True,
              help="Terrarium tile zoom (8=coarse, 12=detail, more downloads)")
@click.option("--pack-size", type=int, default=512, show_default=True, help=".rte grid edge")
@click.option(
    "--peak-game-y",
    type=int,
    default=None,
    help="Staged synthetic peak at this game Y (e.g. 500). Skips Everest DEM.",
)
@click.option("--install", is_flag=True, help="Copy world + pack into Steam/Proton paths")
def height_test_map_cmd(
    repo: str | None,
    size: int,
    source: str,
    terrarium_zoom: int,
    pack_size: int,
    peak_game_y: int | None,
    install: bool,
) -> None:
    """Generate height-test pack + baked world.

    Default: real Everest DEM. Use --peak-game-y 500 for a staged cone (full solid fill).
    """
    from pathlib import Path

    from realearth.height_test_map import build_all

    root = Path(repo) if repo else Path(__file__).resolve().parents[2]
    info = build_all(
        root,
        world_size=size,
        source=source,
        terrarium_zoom=terrarium_zoom,
        pack_size=pack_size,
        peak_game_y=peak_game_y,
    )
    click.echo(f"Pack:  {info['pack_dir']}")
    click.echo(f"World: {info['world_dir']}")
    p = info["pack"]
    click.echo(f"Sources: {', '.join(p.get('sources') or [])}")
    click.echo(
        f"Peak elev={p['peak_elev_m']:.0f} m  "
        f"1:1 gameY={p['peak_game_y_one_to_one']}  "
        f"engineMaxY={info.get('engine_max_game_y')}  "
        f"stock-DTM clamp={p.get('peak_game_y_stock_1to1_clamped', '?')}"
    )
    if install:
        _install_height_test(
            root,
            Path(info["pack_dir"]),
            Path(info["world_dir"]),
            world_name=str(info.get("world_name") or "RealEarth_HeightTest"),
            engine_max_game_y=int(info.get("engine_max_game_y") or 11000),
        )


def _install_height_test(
    root: Path,
    pack_dir: Path,
    world_dir: Path,
    *,
    world_name: str = "RealEarth_HeightTest",
    engine_max_game_y: int = 11000,
) -> None:
    """Install height-test world + Streamed tile pack for Proton client."""
    import json
    import shutil

    from realearth.proton_paths import client_generated_worlds_targets

    # Prefer meta from pack if present
    ht = pack_dir / "height_test.json"
    summit_lon, summit_lat = 86.925, 27.988
    if ht.is_file():
        meta = json.loads(ht.read_text(encoding="utf-8"))
        world_name = str(meta.get("name") or world_name)
        engine_max_game_y = int(meta.get("engine_max_game_y") or engine_max_game_y)
        summit_lon = float(meta.get("summit_lon") or summit_lon)
        summit_lat = float(meta.get("summit_lat") or summit_lat)

    game = Path.home() / ".local/share/Steam/steamapps/common/7 Days To Die"
    mod = game / "Mods" / "RealEarth"
    if mod.is_dir():
        dest_tiles = mod / "Data" / "tiles"
        dest_tiles.mkdir(parents=True, exist_ok=True)
        for child in list(dest_tiles.iterdir()):
            if (
                child.name in ("tiles", "earth.manifest.json", "height_test.json")
                or child.suffix in (".json", ".png")
            ):
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink(missing_ok=True)
        shutil.copytree(pack_dir / "tiles", dest_tiles / "tiles", dirs_exist_ok=True)
        for name in ("earth.manifest.json", "height_test.json", "preview_elev_m.png"):
            src = pack_dir / name
            if src.is_file():
                shutil.copy2(src, dest_tiles / name)
        cfg_path = mod / "Config" / "realearth.json"
        if cfg_path.is_file():
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            cfg["MapMode"] = "Streamed"
            cfg["EnableEngineHeightMod"] = True
            cfg["EngineMaxGameY"] = int(engine_max_game_y)
            cfg["EngineHeightOneToOne"] = True
            cfg["EngineHeightPreferVanillaCeiling"] = False
            cfg["TilePackPath"] = "Data/tiles"
            cfg["WorldWidth"] = 512
            cfg["WorldHeight"] = 512
            cfg["TileSize"] = 512
            cfg["LocalWindowSize"] = 512
            cfg["EnableLongitudeWrap"] = False
            cfg["DefaultSpawnLon"] = summit_lon
            cfg["DefaultSpawnLat"] = summit_lat
            cfg["SpawnLongitude"] = summit_lon
            cfg["SpawnLatitude"] = summit_lat
            cfg["DebugRevealFullMap"] = True
            man_path = pack_dir / "earth.manifest.json"
            if man_path.is_file():
                man = json.loads(man_path.read_text(encoding="utf-8"))
                ww = int(man.get("world_width") or 512)
                wh = int(man.get("world_height") or 512)
                cfg["WorldWidth"] = ww
                cfg["WorldHeight"] = wh
                cfg["TileSize"] = int(man.get("tile_size") or ww)
                cfg["LocalWindowSize"] = min(ww, wh)
                bbox = man.get("bbox") or {}
                if bbox:
                    cfg["BboxWest"] = float(bbox["west"])
                    cfg["BboxSouth"] = float(bbox["south"])
                    cfg["BboxEast"] = float(bbox["east"])
                    cfg["BboxNorth"] = float(bbox["north"])
            cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
        click.echo(f"Installed tile pack → {dest_tiles}")
        click.echo(
            f"Config MapMode=Streamed world={world_name} EngineMaxGameY={engine_max_game_y}. "
            "Requires: make engine-expand (YDim=16384)."
        )

    for gw in client_generated_worlds_targets(prefer_proton=True, also_native=True):
        dest = Path(gw) / world_name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(world_dir, dest)
        click.echo(f"Installed world → {dest}")

    click.echo(f"Play: New Game → {world_name}")


@main.command("height-mod-test")
def height_mod_test_cmd() -> None:
    """Small targeted test case for the engine height mod (Everest + fly-over).

    Prints PASS/FAIL lines for sea, Everest summit, fly-over, ceiling clamp, trench.
    Exit code 0 if all pass. Also covered by: pytest tests/test_height_mod_case.py
    """
    from realearth.height_mod_case import all_passed, format_report, run_height_mod_case

    results = run_height_mod_case()
    click.echo(format_report(results), nl=False)
    if not all_passed(results):
        raise SystemExit(1)


@main.command("engine-audit")
@click.option(
    "--dll",
    type=click.Path(exists=True),
    default=None,
    help="Assembly-CSharp.dll (default: Steam 7DTD Managed)",
)
def engine_audit_cmd(dll: str | None) -> None:
    """Probe vanilla vertical engine constants (ChunkBlockYDim, layers, cMaxHeight).

    Confirms why RealEarth needs an engine-height module for true tall mountains:
    stock 3.0.x is a fixed 256-block column (compile-time literals).
    """
    from pathlib import Path

    from realearth.engine_constants import audit_engine_height

    report = audit_engine_height(Path(dll) if dll else None)
    click.echo(f"dll: {report['dll']} exists={report['exists']}")
    click.echo("constants:")
    for k, v in sorted((report.get("constants") or {}).items()):
        click.echo(f"  {k} = {v}")
    click.echo(f"needs_engine_mod_for_taller: {report['needs_engine_mod_for_taller']}")
    for n in report.get("notes") or []:
        click.echo(f"note: {n}")


@main.command("sample-chunk")
@click.option("--pack", "pack_dir", type=click.Path(exists=True), required=True,
              help="Tile pack (earth.manifest.json + tiles/tz/tx.rte)")
@click.option("--lon", type=float, default=None, help="Sample near longitude (uses pack bbox)")
@click.option("--lat", type=float, default=None, help="Sample near latitude")
@click.option("--x", "origin_x", type=int, default=None, help="Pack/Earth chunk origin X")
@click.option("--z", "origin_z", type=int, default=None, help="Pack/Earth chunk origin Z")
@click.option("--size", "chunk_size", type=int, default=16, show_default=True,
              help="Vanilla chunk edge (blocks)")
def sample_chunk_cmd(
    pack_dir: str,
    lon: float | None,
    lat: float | None,
    origin_x: int | None,
    origin_z: int | None,
    chunk_size: int,
) -> None:
    """Fill one Streamed chunk (heights + landcover) from .rte samples.

    Proves the offline inject path used by runtime ChunkTerrainSampler:
    pack XZ → decode tile → compress elevation → 16×16 game heights.
    """
    from realearth.streamed_chunk import (
        demo_pack_chunk_at_lonlat,
        fill_chunk_heights,
        fill_chunk_landcover,
        load_pack_manifest,
    )

    if (lon is None) != (lat is None):
        raise click.ClickException("--lon and --lat must be given together")
    if (origin_x is None) != (origin_z is None):
        raise click.ClickException("--x and --z must be given together")
    if lon is not None and origin_x is not None:
        raise click.ClickException("choose one location mode: --lon/--lat or --x/--z, not both")

    pack = Path(pack_dir)
    if lon is not None:
        _require_finite("--lon", lon)
        _require_finite("--lat", lat)
        info = demo_pack_chunk_at_lonlat(pack, lon, lat, chunk_size=chunk_size)
        click.echo(f"lon/lat {lon} {lat} → pack earth {info['earth']}")
        click.echo(f"window origin {info['origin']} chunk_local {info['chunk_local']}")
        click.echo(
            f"heights min={info['height_min']} mid={info['height_mid']} max={info['height_max']} "
            f"landcover_mid={info['landcover_mid']}"
        )
        return

    man = load_pack_manifest(pack)
    sea = man.sea_level_game_y if man else DEFAULT_SEA_LEVEL_GAME_Y
    # default origin: (0,0)
    ox = origin_x if origin_x is not None else 0
    oz = origin_z if origin_z is not None else 0

    heights = fill_chunk_heights(pack, ox, oz, chunk_size=chunk_size, sea_level_y=sea)
    lc = fill_chunk_landcover(pack, ox, oz, chunk_size=chunk_size)
    mid = chunk_size // 2
    click.echo(f"chunk origin ({ox},{oz}) size={chunk_size}")
    click.echo(
        f"heights min={int(heights.min())} mid={int(heights[mid, mid])} max={int(heights.max())} "
        f"landcover_mid={int(lc[mid, mid])}"
    )


@main.command("window-slide")
@click.option("--size", type=int, default=1024, show_default=True,
              help="Local window edge in blocks")
@click.option("--earth-x", type=int, required=True, help="Absolute Earth X to center on")
@click.option("--earth-z", type=int, required=True, help="Absolute Earth Z to center on")
@click.option(
    "--local-x", type=int, default=None,
    help="Player local X (default: near edge to force slide)",
)
@click.option("--local-z", type=int, default=None,
              help="Player local Z (default: window mid-row)")
@click.option("--no-wrap", is_flag=True, help="Disable longitude wrap")
def window_slide_cmd(
    size: int,
    earth_x: int,
    earth_z: int,
    local_x: int | None,
    local_z: int | None,
    no_wrap: bool,
) -> None:
    """Exercise continuous local↔absolute + origin slide (WorldSession math)."""
    from realearth.local_window import LocalWindow

    g = EarthGrid()
    win = LocalWindow(grid=g, size=size, enable_longitude_wrap=not no_wrap)
    win.center_on_absolute(earth_x, earth_z)
    lx = local_x if local_x is not None else size - 10
    lz = local_z if local_z is not None else size // 2
    # place player at given local on current window
    abs_before = win.local_to_earth(lx, lz)
    slid, nx, nz, ax, az = win.tick_player_local(lx, lz, allow_slide=True)
    back = win.earth_to_local(ax, az)
    click.echo(f"centered origin=({win.origin_x},{win.origin_z}) size={size}")
    click.echo(f"player local before=({lx},{lz}) absolute={abs_before}")
    click.echo(f"slid={slid} new_local=({nx},{nz}) absolute=({ax},{az})")
    click.echo(f"roundtrip earth_to_local={back}")


@main.command("bake-world")
@click.option("--pack", "pack_dir", type=click.Path(exists=True), required=True,
              help="Tile pack with earth.manifest.json")
@click.option("--out", "out_dir", type=click.Path(), required=True,
              help="Output folder for one continuous world")
@click.option("--size", type=int, default=4096, show_default=True,
              help="World edge in blocks (2048–16384, snapped to mult of 2048)")
@click.option("--name", default=None, help="World display name")
@click.option("--sea-level", "sea_level_y", type=int, default=32, show_default=True,
              help="Sea level in game Y blocks")
@click.option(
    "--generated/--heightmap-only",
    default=True,
    help="Write full GeneratedWorlds folder (dtm.raw + map_info.xml + …) vs PNG-only",
)
@click.option(
    "--ttw-template",
    type=click.Path(exists=True),
    default=None,
    help="Optional main.ttw template (defaults to first GeneratedWorlds sample)",
)
def bake_world_cmd(
    pack_dir: str,
    out_dir: str,
    size: int,
    name: str | None,
    sea_level_y: int,
    generated: bool,
    ttw_template: str | None,
) -> None:
    """Bake ONE continuous playable map for in-game use (single save / single world)."""
    from realearth.bake_world import bake_world_from_pack, planet_scale_for_size, snap_world_size
    from realearth.generated_world import bake_generated_world

    size = snap_world_size(size)
    world_name = name or "RealEarth"
    if generated:
        meta = bake_generated_world(
            Path(pack_dir),
            Path(out_dir),
            size=size,
            name=world_name,
            sea_level_y=sea_level_y,
            ttw_template=Path(ttw_template) if ttw_template else None,
        )
        click.echo(f"GeneratedWorld → {out_dir}")
        click.echo(f"  size: {meta['size']} x {meta['size']}  dtm_bytes={meta['dtm_bytes']}")
        click.echo("  files: dtm.raw dtm_processed.raw biomes.png map_info.xml spawnpoints.xml …")
        click.echo(
            "  install: copy folder to ~/.local/share/7DaysToDie/"
            f"GeneratedWorlds/{Path(out_dir).name}"
        )
        click.echo("  then New Game → select that world (one continuous map).")
    else:
        result = bake_world_from_pack(
            Path(pack_dir),
            Path(out_dir),
            size=size,
            name=world_name,
            sea_level_y=sea_level_y,
        )
        click.echo(f"Heightmap export → {result['out_dir']}")
        click.echo(f"  heightmap: {result['heightmap']}")
    click.echo(f"  tip: full Earth in {size} blocks ≈ {planet_scale_for_size(size):.0f} m/block")


@main.command("export-viewer")
@click.option("--pack", "pack_dir", type=click.Path(exists=True), required=True,
              help="Tile pack directory (earth.manifest.json + tiles/)")
@click.option("--out", "out_dir", type=click.Path(), required=True,
              help="Output directory (viewer/data/<name>)")
@click.option("--max-dim", type=int, default=2048, show_default=True,
              help="Longest side of exported PNGs")
@click.option("--name", default=None, help="Display name override")
def export_viewer_cmd(pack_dir: str, out_dir: str, max_dim: int, name: str | None) -> None:
    """Export PNG mosaics + viewer.json for the web map viewer."""
    from realearth.viewer_export import export_viewer_pack

    path = export_viewer_pack(Path(pack_dir), Path(out_dir), max_dim=max_dim, name=name)
    click.echo(f"Viewer pack → {path}")
    click.echo("  hybrid.png elevation.png landcover.png population.png viewer.json")


@main.command("serve")
@click.option("--port", type=int, default=8765, show_default=True)
@click.option("--bind", default="127.0.0.1", show_default=True)
@click.option(
    "--root",
    type=click.Path(exists=True),
    default=None,
    help="Directory to serve (default: repo viewer/ next to tools/)",
)
@click.option(
    "--no-browser",
    is_flag=True,
    default=False,
    help="Do not open the web browser (scripts / SSH)",
)
def serve_cmd(port: int, bind: str, root: str | None, no_browser: bool) -> None:
    """Serve the web map viewer (static files)."""
    from realearth.viewer_server import serve

    if root:
        serve_root = Path(root).resolve()
    else:
        # tools/realearth/cli.py → repo/viewer
        serve_root = Path(__file__).resolve().parents[2] / "viewer"
        if not serve_root.is_dir():
            serve_root = Path.cwd() / "viewer"
    if not serve_root.is_dir():
        raise click.ClickException(f"viewer root not found: {serve_root}")

    serve(port=port, bind=bind, directory=serve_root, open_browser=not no_browser)


if __name__ == "__main__":
    main(sys.argv[1:])
