"""Structural rules for the Everest-scale engine height patcher (shipped source).

Does not load Mono.Cecil against the live game DLL (not in CI). Verifies the
patcher Program.cs still encodes the safety rules that fixed production crashes.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATCHER = ROOT / "tools" / "engine_patcher" / "Program.cs"


def _src() -> str:
    assert PATCHER.is_file(), f"missing {PATCHER}"
    return PATCHER.read_text(encoding="utf-8")


def test_everest_scale_ydim_is_16384():
    src = _src()
    # Default Everest-scale; --ydim can override at runtime
    assert "TargetYDim = 16384" in src
    assert "TargetYPow = 14" in src
    assert "--ydim" in src
    assert "SetYDim" in src


def test_layer_counts_rewritten_unconditionally_on_storage_types():
    """Mismatched alloc vs free of layer count caused native Free crashes."""
    src = _src()
    assert "IsLayerStorageType(type)" in src
    # Must not only rewrite some 64s via look-ahead that misses Dispose free sizes
    assert "replace = TargetLayers" in src
    assert "UnsafeChunkData" in src
    assert "ChunkBlockChannel" in src


def test_skips_static_ctor_and_xz_maps():
    src = _src()
    assert 'method.Name == ".cctor"' in src
    assert "IsXzMapSizeSite" in src
    assert "m_HeightMap" in src
    assert "ChunkAreaDim" in src or "XZ" in src


def test_water_volume_scales_with_ydim():
    src = _src()
    assert "TargetVolumeBits" in src
    assert "16 * 16 * TargetYDim" in src
    assert 'type.Name == "WaterDataHandle"' in src


def test_worldsession_disables_slide_on_full_window():
    ws = ROOT / "Source" / "RealEarth" / "WorldSession.cs"
    src = ws.read_text(encoding="utf-8")
    # Slide is disabled by clamping the origin when the window covers the world.
    assert "WorldWidth - LocalWindowSize" in src
    assert "SingleWorldSession" in src


def test_modlet_stock_safe_config_default():
    """YDim expand is part of RealEarth; stock compress is fallback only."""
    cfg = (ROOT / "Config" / "realearth.json").read_text(encoding="utf-8")
    assert "EngineHeightStockSafe" in cfg
    assert (ROOT / "docs" / "MODLET.md").is_file()
    assert (ROOT / "scripts" / "apply_engine_expand.sh").is_file()
    modlet = (ROOT / "docs" / "MODLET.md").read_text(encoding="utf-8")
    assert "YDim expand" in modlet
    mod = (ROOT / "Source" / "RealEarth" / "EngineHeight" / "EngineHeightMod.cs").read_text(
        encoding="utf-8"
    )
    assert "RealEarth YDim expand" in mod
    assert "OPT-IN compress on stock" in mod


def test_rerun_never_labels_expanded_dll_as_stock():
    """Idempotency: --force with no backup must not copy an expanded DLL as 'stock'
    (that would poison engine-restore). Backup is taken only after analysis finds
    real work, while gameDll is still unmodified."""
    src = _src()
    # No eager pre-analysis backup creation
    assert "!File.Exists(bak) && !dryRun)" not in src
    # Order: analyze -> detect already-at-target -> backup -> write
    assert src.index("constant table rewrites") < src.index("atTarget > 0")
    assert src.index("atTarget > 0") < src.index("Backup written")
    assert src.index("Backup written") < src.index("module.Write()")


def test_marker_healed_after_crash_between_write_and_marker():
    """Crash between module.Write() and marker creation leaves a patched DLL without
    a marker; a plain re-run must recognize it (constants at target) and restore
    the marker instead of failing with exit 3."""
    src = _src()
    assert "atTarget" in src
    assert "atTarget++" in src
    assert "Marker restored" in src


def test_marker_records_dll_sha256_and_verify_mode_detects_drift():
    """Post-expand drift detection (docs/THREAT_MODEL.md T5 residual): every marker
    records the sha256 of the DLL as expanded, and --verify compares current bytes
    against it without analyzing or writing the DLL."""
    src = _src()
    marker_body = src[src.index("static void WriteMarker") :]
    assert "Sha256Hex(File.ReadAllBytes(gameDll))" in marker_body
    assert 'line.StartsWith("sha256="' in src
    assert "VerifyAgainstMarker" in src
    # Verify must run before any write path and never reach ModuleDefinition.ReadModule.
    assert src.index("if (verify)") < src.index("ModuleDefinition.ReadModule")
    assert '"--verify"' in src


def test_stale_marker_after_update_does_not_block_reexpand():
    """A Steam update/verify replaces the expanded DLL with new stock: the old
    marker's sha no longer matches, so "already patched" must not fire and the
    stale .re_stock_bak (previous build) must be refreshed onto the current
    stock before re-patching. Restoring the old backup would downgrade the game."""
    src = _src()
    # Already-patched gate compares marker sha to the current DLL sha
    assert "markerSha == currentSha" in src
    # Stale marker path re-applies instead of refusing
    assert "Stale expand marker" in src
    # Backup refresh is guarded by "current is stock" (readable and not expanded
    # to target), so an expanded or unreadable DLL can never be relabeled as stock.
    assert "ReadChunkBlockYDim(gameDll)" in src
    assert "currentYDim > 0 && currentYDim != TargetYDim" in src
    assert "backup refreshed to the current build" in src
    # The refresh must happen before the restore-from-backup step.
    assert src.index("backup refreshed") < src.index("Restoring stock from backup")
    assert "ReadMarkerSha" in src
