"""Structural assertions on the shipped C# observability surface.

Pins the properties an operator depends on in a server log:
- tile load failures are budgeted, never one ERROR per tile per miss window
- a tile load reports its wall time, so a slow CDN is distinguishable from a dead one
- the `reinject` command surfaces both, plus what the log budgets refused to print
- init-time failures carry the stack, not just type and message
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "Source" / "RealEarth"


def _read(rel: str) -> str:
    return (SRC / rel).read_text(encoding="utf-8")


def test_tile_streamer_never_logs_load_failure_unbudgeted():
    """One unreadable tile root must not put an ERROR per tile into the server log."""
    src = _read("TileStreamer.cs")
    assert "LogLoadError" in src, "TileStreamer must route load failures through its budget"
    helper = re.search(r"static void LogLoadError\(string msg\).*?\n        \}", src, re.S)
    assert helper, "LogLoadError helper not found"
    sites = src[: helper.start()] + src[helper.end() :]
    for m in re.finditer(r"ModApi\.Log(?:Error|Warn)\(", sites):
        line = sites[: m.start()].count("\n") + 1
        raise AssertionError(
            f"TileStreamer.cs:{line} logs a tile-load failure directly; "
            "use LogLoadError so the budget can cap and count it"
        )


def test_load_budget_counts_what_it_refuses_to_print():
    src = _read("LogBudget.cs")
    assert "Suppressed" in src, "a spent budget must stay countable"
    streamer = _read("TileStreamer.cs")
    assert "LoadErrorBudget" in streamer
    stats = _read("TileLoadStats.cs")
    assert (
        "public static void Reset()" in stats
    ), "reinject reset must clear the tile-load counters, including the new times"
    assert "TileLoadStats.Reset()" in _read("ConsoleCmdReInject.cs")
    assert re.search(
        r"static void LogLoadError\(string msg\)\s*\{\s*if \(LoadErrorBudget\.Allow\(\)\)",
        streamer,
    ), "LogLoadError must gate on the budget"


def test_successful_tile_loads_record_elapsed_time():
    """Counters alone cannot tell a slow CDN from a fast failing one."""
    stats = _read("TileLoadStats.cs")
    assert "AddDiskOk(long elapsedMs" in stats
    assert "AddCdnOk(long elapsedMs" in stats
    assert "DiskMaxMs" in stats and "CdnMaxMs" in stats
    streamer = _read("TileStreamer.cs")
    assert "Stopwatch.StartNew()" in streamer
    for call in ("AddDiskOk(sw.ElapsedMilliseconds)", "AddCdnOk(sw.ElapsedMilliseconds)"):
        assert call in streamer, f"no timing passed to {call}"


def test_reinject_reports_load_latency_and_suppressed_lines():
    src = _read("ConsoleCmdReInject.cs")
    assert "InjectPatchStats.FormatSummary()" in src, "reinject must print the tile counters"
    assert "SuppressedLogSummary" in src, (
        "reinject must report lines the log budgets refused to print, "
        "otherwise a truncated log reads as a failure that stopped"
    )
    hooks = _read("RuntimeHooks.cs")
    assert "public static string SuppressedLogSummary()" in hooks


def test_init_failures_carry_the_stack():
    """Init/patch/save paths fire once: the operator has no debugger, so keep the stack."""
    mod = _read("ModApi.cs")
    assert "internal static string Describe(Exception ex)" in mod
    assert "stack.Split" in mod, "Describe must render the stack chain"
    for rel, needle in (
        ("ModApi.cs", 'LogError("RealEarth failed to init", ex)'),
        ("ModApi.cs", 'LogWarn("Harmony bootstrap skipped", hex)'),
        ("ModApi.cs", 'LogWarn("RuntimeHooks skipped", rex)'),
        ("ModApi.cs", 'LogWarn("BuildGuard skipped", gex)'),
        ("HarmonyBootstrap.cs", 'ModApi.LogError("HarmonyBootstrap", ex)'),
        ("SessionStateStore.cs", 'ModApi.LogError("SessionStateStore.TryLoad", ex)'),
    ):
        assert needle in _read(rel), f"{rel} must log the full exception: {needle}"


def test_budgeted_tick_paths_keep_the_compact_form():
    """A per-tick failure must stay one short line: no stack frames at volume."""
    src = _read("RuntimeHooks.cs")
    for m in re.finditer(r"Log(?:Error|Warn)\((.*?)\);", src, re.S):
        assert "ex)" not in m.group(1) or "Describe" in m.group(
            1
        ), "budgeted tick-path lines must not embed a stack trace"
