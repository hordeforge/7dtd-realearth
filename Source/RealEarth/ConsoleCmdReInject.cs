using System.Collections.Generic;

namespace RealEarth
{
    /// <summary>F1: inject / fail-closed / patch bind diagnostics (P0–P1).</summary>
    public class ConsoleCmdReInject : ConsoleCmdAbstract
    {
        public override string[] getCommands() => new[] { "reinject", "re_inject", "re_heightinject" };

        public override string getDescription() =>
            "RealEarth: height inject stats (patches, missing tiles, session peak)";

        public override string getHelp() =>
            "reinject          print inject patch binds + sample counters\n" +
            "reinject reset    clear sample and tile-load counters (not Harmony binds)\n" +
            "P1 needs height and/or GenerateTerrain patches bound after world load.";

        public override void Execute(List<string> _params, CommandSenderInfo _senderInfo)
        {
            string sub = (_params != null && _params.Count > 0) ? _params[0].ToLowerInvariant() : "status";
            if (sub == "reset")
            {
                TileSamplePolicy.ResetCounters();
                TileLoadStats.Reset();
                ConsoleOut.Out("[RealEarth] reinject: sample and tile-load counters cleared.");
                return;
            }

            var cfg = ModApi.Config;
            ConsoleOut.Out("[RealEarth] " + InjectPatchStats.FormatSummary());
            ConsoleOut.Out($"  MapMode={cfg?.MapMode} FailClosedMissingTiles={cfg?.FailClosedMissingTiles} " +
                $"StockSafe={cfg?.EngineHeightStockSafe} SeaY={cfg?.SeaLevelGameY}");
            ConsoleOut.Out(
                $"  minimalInjectBinding={InjectPatchStats.HasMinimalInjectBinding} " +
                $"productInjectBinding={InjectPatchStats.HasProductInjectBinding} " +
                $"injectBlocked={ChunkTerrainInject.InjectBlocked}");
            // Lines the hot paths refused to print. Nonzero here means the log above
            // understates the failure rate, not that the failures stopped.
            ConsoleOut.Out("  suppressedLogLines(" + HooksImpl.SuppressedLogSummary() + ")");
            ConsoleOut.Out(
                $"  dualFillMax={ChunkTerrainInject.EffectiveFullDualFillMaxSurface()} " +
                $"sessionPeak={ChunkTerrainInject.SessionPeakHeight} " +
                $"blocksOk={ChunkTerrainInject.SessionBlocksApplied}");
            int yDim = EngineHeight.EngineHeightMod.Probe?.ChunkBlockYDim ?? 256;
            ConsoleOut.Out(
                $"  expand={ExpandProductGuard.DescribeHeightMode(cfg?.EnableEngineHeightMod ?? true, cfg?.EngineHeightStockSafe ?? false, yDim)} " +
                $"needsExpand={ExpandProductGuard.RequiresExpandForRealHeight(cfg?.EngineHeightStockSafe ?? false, cfg?.EngineHeightOneToOne ?? true, yDim)} " +
                $"productHeightBlocked={EngineHeight.EngineHeightMod.ProductHeightBlocked}");
            ConsoleOut.Out(
                $"  densityBudget maxPerChunk={DensityBudget.DefaultMaxPrefabsPerChunk} " +
                $"cdnBase={(string.IsNullOrEmpty(cfg?.TileCdnBaseUrl) ? "none" : "set")} " +
                $"hotTiles={ModApi.Streamer?.HotTileCount ?? 0} foci={ModApi.Streamer?.FocusCount ?? 0}");
            if (EngineHeight.EngineHeightMod.Active)
                ConsoleOut.Out($"  EngineHeightMod=Active allocY={EngineHeight.EngineHeightMod.AllocatableColumnMaxY}");
            else
                ConsoleOut.Out("  EngineHeightMod=inactive (stock YDim or disabled)");
        }
    }
}
