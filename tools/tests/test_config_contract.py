"""Config contract between shipped scripts, mod config, and C# loader.

Pins the product defaults so install/package scripts cannot drift back to
debug-on or StockSafe-on fallbacks (HEIGHT_LIMITS.md: StockSafe is not product).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "Source" / "RealEarth"


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_install_script_defaults_stocksafe_off():
    """install_proton.sh must fall back to EngineHeightStockSafe=false (product rule)."""
    src = _read("scripts/install_proton.sh")
    assert '"EngineHeightStockSafe?=false"' in src, (
        "install_proton.sh must default EngineHeightStockSafe to false "
        "(real meters are the product path; true silently compresses heights)"
    )


def test_packaged_config_ships_debug_fow_off():
    """package_mod.sh must ship with debug FOW keys off."""
    src = _read("scripts/package_mod.sh")
    assert '"DebugRevealFullMap?=false"' in src
    assert '"DebugMapRevealRadiusChunks?=0"' in src


def test_init_publishes_config_only_after_in_place_clamps():
    """Config is read by the chunk-generation thread and the tile-load workers.

    InitMod clamps LocalWindowSize and lets EngineHeightMod.Init settle
    EngineMaxGameY / the one-to-one flag on the config object in place, so
    publishing Config before those writes would let a worker sample a
    half-applied profile (some chunks capped at 255, others at 32767).
    """
    api = _read("Source/RealEarth/ModApi.cs")
    load = api.index("RealEarthConfig cfg = loadedConfig.Config;")
    clamp = api.index("cfg.LocalWindowSize = cfg.WorldWidth;", load)
    height = api.index("EngineHeightMod.Init(cfg);", clamp)
    publish = api.index("Config = cfg;", height)
    first_use = api.index("new EarthCoords(", height)
    assert load < clamp < height < first_use < publish, (
        "InitMod must clamp the config and run the engine-height policy before "
        "publishing it, and only then hand the config to EarthCoords/TileStreamer/"
        "WorldSession"
    )


def test_cross_thread_statics_are_volatile():
    """Statics the gen thread and tile-load workers read must be published, not
    plain: a stale Config/Streamer or a stale BuildGuard verdict is exactly what
    the fail-closed gate and the height cap exist to prevent."""
    api = _read("Source/RealEarth/ModApi.cs")
    for field in (
        "static volatile string _modPath",
        "static volatile RealEarthConfig? _config",
        "static volatile TileStreamer? _streamer",
        "static volatile EarthCoords? _coords",
        "static volatile WorldSession? _session",
    ):
        assert field in api, f"ModApi.{field} must be volatile"

    height = _read("Source/RealEarth/EngineHeight/EngineHeightMod.cs")
    assert "static volatile WorldConstantsProbe? _probe" in height
    assert "static volatile EngineHeightPolicy? _policy" in height
    assert "static volatile bool _productHeightBlocked" in height

    transpiler = _read("Source/RealEarth/RuntimeYDimTranspiler.cs")
    assert "public static volatile bool IsActive;" in transpiler
    assert "public static volatile int PatchCount;" in transpiler

    guard = _read("Source/RealEarth/BuildGuard.cs")
    assert "public static volatile bool Blocked;" in guard
    assert "public static volatile bool Guarded;" in guard


def test_lazy_reflection_resolve_publishes_last():
    """A "resolved" flag written before the handles it guards is a check-then-act
    race: a second thread returns early and caches a permanently empty handle set.
    Both HUD tick resolvers must set the flag after publishing the handles."""
    for rel, marker in (
        ("Source/RealEarth/AltitudeClimateTick.cs", "AltitudeClimateTick resolve"),
        ("Source/RealEarth/LonLatHudTick.cs", "LonLatHudTick resolve"),
    ):
        src = _read(rel)
        guard = src.index("if (_resolved) return;")
        catch = src.index("catch (Exception ex)", guard)
        publish = src.index("_resolved = true;", catch)
        assert (
            guard < catch < publish
        ), f"{rel}: _resolved must be set after the resolve body, never before it"
        assert src.index(marker) > 0


def test_no_shell_script_embeds_python():
    """Config writing lives in realearth.mod_config / realearth.server_config.

    A heredoc splices shell values into a Python source body, so a world name or
    path holding a quote becomes executable code; it also puts the logic beyond
    the reach of these tests.
    """
    for path in sorted((ROOT / "scripts").glob("*.sh")):
        src = path.read_text(encoding="utf-8")
        assert not re.search(
            r"python3?\s+(-c|-\s*<<)", src
        ), f"{path.name} embeds python; call a realearth module instead"


def test_height_pack_install_ships_stocksafe_off():
    """install_height_pack.sh must not opt installs into StockSafe compress
    (HEIGHT_LIMITS.md: operator opt-in only; silent 0-250 squash otherwise)."""
    src = _read("scripts/install_height_pack.sh")
    assert '"EngineHeightStockSafe=false"' in src, (
        "install_height_pack.sh must write EngineHeightStockSafe=false "
        "(unexpanded engines must hit the loud ExpandProductGuard, not compress)"
    )
    for path in sorted((ROOT / "scripts").glob("*.sh")):
        assert "EngineHeightStockSafe=true" not in path.read_text(
            encoding="utf-8"
        ), f"{path.name} forces EngineHeightStockSafe=true (not product)"


def test_install_script_validates_map_mode():
    """MAP_MODE other than Streamed|Baked must fail the install, not become Baked."""
    src = _read("scripts/install_proton.sh")
    assert re.search(r"Streamed\|Baked\)", src), "MAP_MODE case validation missing"


def test_shipped_configs_match_product_defaults():
    """Shipped realearth.json profiles keep real-height on and debug FOW off
    (advanced_height.json is the documented dev template and may differ)."""
    for name in ("realearth.json", "realearth.mp.json"):
        cfg = json.loads(_read(f"Config/{name}"))
        assert cfg["MapMode"] in ("Streamed", "Baked"), name
        assert cfg["MultiplayerOriginMode"] in (
            "SoloSlide",
            "SharedFixed",
            "SharedSlide",
        ), name
        assert cfg["EnableEngineHeightMod"] is True, name
        assert cfg["EngineHeightStockSafe"] is False, name
        assert cfg["DebugRevealFullMap"] is False, name
        assert cfg["DebugMapRevealRadiusChunks"] == 0, name
        assert cfg["UnloadRadiusTiles"] > cfg["StreamRadiusTiles"], name


def test_config_validate_exists_and_runs_at_init():
    """RealEarthConfig.Validate() must clamp/warn and be called during init.

    The manifest overlay sits between Load and Validate on purpose: pack
    earth.manifest.json overrides world size and bbox, so Validate has to see
    the final values (ModApi.InitMod). Pin that order, not adjacency.
    """
    src = _read("Source/RealEarth/RealEarthConfig.cs")
    assert "public IReadOnlyList<string> Validate()" in src
    # Enum-like strings must list valid values in the warning text.
    for token in ("Streamed", "Baked", "SoloSlide", "SharedFixed", "SharedSlide"):
        assert token in src
    # Unload radius must be forced above stream radius (thrash guard).
    assert "UnloadRadiusTiles = StreamRadiusTiles + 1" in src
    # InitMod must validate at load time, before the config is handed to
    # EarthCoords / TileStreamer / WorldSession. The manifest step sits between
    # Load and Validate on purpose: wrap auto-enable reads the manifest's
    # WorldWidth and regional bbox, so validating earlier would clamp against
    # the shipped placeholders.
    api = _read("Source/RealEarth/ModApi.cs")
    load = api.index("RealEarthConfig.Load(configPath)")
    manifest = api.index("TryApplyPackManifest(tileRoot, cfg);")
    validate = api.index("foreach (var warning in cfg.Validate())")
    first_use = api.index("new EarthCoords(", validate)
    assert load < manifest < validate < first_use, (
        "InitMod must Load, then apply the pack manifest, then run Config.Validate() "
        "in InitMod, after the pack manifest and before the config is used"
    )


def test_config_validate_cross_field_guards():
    """Validate() must flag contradictory/inert dependent configuration.

    A single key is valid alone but dangerous or inert next to another; these
    guards turn silent misconfiguration into a startup warning. Pin the message
    text so the logic cannot be dropped without the test going red.
    """
    src = _read("Source/RealEarth/RealEarthConfig.cs")
    assert "EngineHeightStockSafe && !EnableEngineHeightMod" in src
    assert "EngineHeightStockSafe && EngineHeightOneToOne" in src
    assert 'MapMode.Equals("Baked"' in src and "EnableLongitudeWrap" in src
    assert "RuntimePoiMaxPerArea > 80" in src


def _csharp_config_members() -> set[str]:
    """[DataMember] property names the C# loader actually deserializes."""
    src = _read("Source/RealEarth/RealEarthConfig.cs")
    return set(re.findall(r"\[DataMember\]\s*public\s+\S+\s+(\w+)\s*\{", src))


def test_missing_config_is_reported_not_silent():
    """A missing realearth.json must be named at init, not run as silent defaults.

    Load() writes a defaults file when none exists so a fresh install has one to
    edit, but every value the session then runs was chosen by nobody. The load
    result has to reach the log or a server with a mis-copied Config directory
    looks configured.
    """
    cfg_src = _read("Source/RealEarth/RealEarthConfig.cs")
    assert (
        "public static LoadResult Load(string path)" in cfg_src
    ), "Load must return a result that says the values came from built-in defaults"
    assert "public bool SynthesizedDefaults { get; }" in cfg_src
    api = _read("Source/RealEarth/ModApi.cs")
    assert "RealEarthConfig.Load(configPath);" in api
    assert (
        "loadedConfig.SynthesizedDefaults" in api
    ), "InitMod must warn when it is running built-in config defaults"
    assert api.index("RealEarthConfig.Load(configPath);") < api.index(
        "loadedConfig.SynthesizedDefaults"
    ), "the synthesized-defaults warning must fire right after the load"


def test_shipped_reveal_radius_within_csharp_clamp():
    """Every shipped config must survive RealEarthConfig.Validate unchanged.

    Validate clamps DebugMapRevealRadiusChunks to [0, 64], so a shipped
    profile above the bound loads as a different value than the file says,
    with only a log warning: the dev template shipped 128 while the clamp was
    added and was silently downgraded on every load.
    """
    src = _read("Source/RealEarth/RealEarthConfig.cs")
    checks = re.findall(r"if \(DebugMapRevealRadiusChunks ([<>]) (\d+)\)", src)
    assert len(checks) == 2, "DebugMapRevealRadiusChunks clamp checks not found"
    bounds = {op: int(value) for op, value in checks}
    assert bounds.get(">") is not None and bounds.get("<") is not None
    upper, lower = bounds[">"], bounds["<"]
    for name in (
        "realearth.json",
        "realearth.mp.json",
        "realearth.advanced_height.json",
    ):
        value = json.loads(_read(f"Config/{name}"))["DebugMapRevealRadiusChunks"]
        assert lower <= value <= upper, (
            f"{name} sets DebugMapRevealRadiusChunks={value}, "
            f"which RealEarthConfig.Validate clamps to [{lower}, {upper}]"
        )


def test_shipped_config_keys_exist_in_csharp_loader():
    """Every shipped realearth.json key must map to a C# [DataMember].

    DataContractJsonSerializer silently drops keys it has no member for, so a
    typo'd or renamed key would do nothing at runtime with no error anywhere.
    Keys prefixed "_" are comment/metadata and exempt.
    """
    members = _csharp_config_members()
    assert "MapMode" in members  # sanity: the regex still matches the schema
    for name in (
        "realearth.json",
        "realearth.mp.json",
        "realearth.advanced_height.json",
    ):
        cfg = json.loads(_read(f"Config/{name}"))
        unknown = sorted(k for k in cfg if not k.startswith("_") and k not in members)
        assert not unknown, f"{name} has keys the mod loader ignores: {unknown}"


# Regional pack bbox; the pack manifest fills it at init, so no profile ships it.
_PROFILE_EXEMPT = frozenset({"BboxWest", "BboxSouth", "BboxEast", "BboxNorth"})


def _csharp_config_defaults() -> dict[str, object]:
    """Default value of every [DataMember] property, keyed by member name.

    Only the literal initializers are read; a member defaulting to a constant
    (MaxHotTiles = DefaultMaxHotTiles) is resolved from the same source.
    """
    src = _read("Source/RealEarth/RealEarthConfig.cs")
    consts = {
        name: value.replace("_", "")
        for name, value in re.findall(r"public const \w+ (\w+) = ([^;]+);", src)
    }
    pattern = re.compile(
        r"\[DataMember\]\s*public\s+(\w+)\s+(\w+)\s*\{\s*get;\s*set;\s*\}\s*=\s*([^;]+);"
    )
    out: dict[str, object] = {}
    for ctype, name, raw in pattern.findall(src):
        literal = raw.strip().rstrip("f")
        if literal in consts:
            literal = consts[literal]
        elif ctype == "string":
            out[name] = literal.strip('"')
            continue
        else:
            # int / double / float / bool literals all parse as JSON scalars.
            literal = literal.replace("_", "")
        out[name] = json.loads(literal)
    return out


def test_shipped_default_profile_matches_csharp_defaults():
    """Config/realearth.json must carry every key the C# loader defines, at the
    same value.

    The profile is the operator-facing copy of the defaults, and the defaults
    also apply when the file is missing. A key added to RealEarthConfig.cs and
    left out of the profile (or shipped at a different value) leaves the two
    descriptions of "the default" disagreeing, and a key the profile drops
    silently reverts to whatever the class says.
    """
    defaults = _csharp_config_defaults()
    assert "MapMode" in defaults  # sanity: the regex still matches the schema
    profile = json.loads(_read("Config/realearth.json"))
    missing = sorted(k for k in defaults if k not in profile and k not in _PROFILE_EXEMPT)
    assert not missing, f"Config/realearth.json is missing keys the mod defines: {missing}"
    drifted = {
        key: (defaults[key], profile[key])
        for key in defaults
        if key in profile and profile[key] != defaults[key]
    }
    assert not drifted, f"Config/realearth.json disagrees with the C# defaults: {drifted}"


def test_every_env_var_read_by_the_build_is_documented():
    """Every environment variable the scripts and pipeline read must be named in
    .env.example.

    An operator knob nothing documents is one they set blind, and a knob added
    to a script after the template was written is invisible from here. Reads are
    matched in their default form (${VAR:-...}), so variables a script sets for
    itself are not mistaken for knobs.
    """
    shell = "".join(
        p.read_text(encoding="utf-8") for p in sorted((ROOT / "scripts").glob("*.sh"))
    ) + _read("Makefile")
    read = set(re.findall(r"\$\{([A-Z][A-Z0-9_]*)[:-]", shell))
    read |= set(
        re.findall(
            r'os\.environ(?:\.get)?\(?\[?"([A-Z][A-Z0-9_]*)"',
            "".join(
                p.read_text(encoding="utf-8")
                for p in sorted((ROOT / "tools" / "realearth").glob("*.py"))
            ),
        )
    )
    assert read, "no env vars found; the scan regex is wrong, not the scripts"
    # The project knob families. Script-local scratch variables (PROTON_UD,
    # SCRATCH_OUT) and build internals (PYTHONPATH, SOURCE_DATE_EPOCH) share the
    # read syntax but are not operator configuration.
    knobs = {
        v
        for v in read
        if v.startswith(("RE_", "SEVENDTD_"))
        or v in {"GAME_DIR", "MAP_MODE", "STEAM_DIR", "DOTNET_ROOT"}
    }
    assert knobs, "the knob scan found nothing; the prefixes are wrong"
    example = _read(".env.example")
    undocumented = sorted(v for v in knobs if v not in example)
    assert not undocumented, f"env vars read but absent from .env.example: {undocumented}"


def test_script_window_default_matches_tools_constant():
    """Shell LOCAL_WINDOW_SIZE defaults must mirror realearth.DEFAULT_LOCAL_WINDOW_SIZE.

    The scripts cannot import the tools package (stdlib-only install path), so the
    1024 default is duplicated as a literal; this pins the copies so they cannot
    drift from the Python constant that names it.
    """
    from realearth import DEFAULT_LOCAL_WINDOW_SIZE

    for rel in ("scripts/install_proton.sh", "scripts/package_mod.sh"):
        src = _read(rel)
        match = re.search(r"^LOCAL_WINDOW_SIZE=(\d+)$", src, re.MULTILINE)
        assert match, f"{rel} lost its LOCAL_WINDOW_SIZE default"
        assert int(match.group(1)) == DEFAULT_LOCAL_WINDOW_SIZE, (
            f"{rel}: LOCAL_WINDOW_SIZE={match.group(1)} != "
            f"realearth.DEFAULT_LOCAL_WINDOW_SIZE={DEFAULT_LOCAL_WINDOW_SIZE}"
        )


def test_package_script_reads_documented_game_dir_knob():
    """package_mod.sh must read SEVENDTD_GAME_DIR then GAME_DIR.

    The Makefile exports GAME_DIR for this script and every other install/expand
    script reads SEVENDTD_GAME_DIR first; any other fallback spelling silently
    drops the DLL from the package.
    """
    src = _read("scripts/package_mod.sh")
    assert 'GAME_DIR="${SEVENDTD_GAME_DIR:-${GAME_DIR:-}}"' in src


def test_loader_reports_unknown_config_keys():
    """A misspelled key is dropped by the serializer, so init must name it."""
    src = _read("Source/RealEarth/RealEarthConfig.cs")
    assert "FindUnknownMemberNames" in src, (
        "RealEarthConfig must expose an unknown-key scan: DataContractJsonSerializer "
        "silently ignores members it has no contract for"
    )
    api = _read("Source/RealEarth/ModApi.cs")
    assert "FindUnknownMemberNames" in api, "ModApi must log unknown config keys at init"
    assert "config: mode=" in api, "ModApi must log the effective profile at init"


def test_wrap_threshold_matches_runtime_auto_enable():
    """Offline writer and runtime must agree on which packs wrap the antimeridian."""
    py = _read("tools/realearth/__init__.py")
    match = re.search(r"PLANET_CANVAS_MIN_WIDTH = ([\d_]+)", py)
    assert match, "PLANET_CANVAS_MIN_WIDTH not found"
    assert int(match.group(1).replace("_", "")) == 40_000_000, (
        "RealEarthConfig.Validate auto-enables longitude wrap at WorldWidth >= 40,000,000; "
        "a lower offline threshold ships wrap=true for packs the mod rejects at init"
    )


def test_manifest_keys_read_by_the_mod_exist_in_the_writer():
    """Every earth.manifest.json key the C# overlay reads must be one the
    offline pipeline writes.

    PackManifest deserializes into a typed DTO, so a renamed or dropped writer
    key reads as null and the pack silently loads at the shipped world size.
    """
    from realearth.tile_format import Manifest

    written = Manifest(bbox={"west": 0.0, "south": 0.0, "east": 1.0, "north": 1.0}).to_dict()
    src = _read("Source/RealEarth/PackManifest.cs")
    read = set(re.findall(r'\[DataMember\(Name = "(\w+)"\)\]', src))
    assert {"world_width", "world_height", "tile_size", "sea_level_game_y", "bbox"} <= read
    missing = sorted(k for k in read if k not in written and k not in written["bbox"])
    assert not missing, f"PackManifest reads manifest keys the writer never emits: {missing}"
