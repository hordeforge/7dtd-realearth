using System;
using System.Collections.Generic;
using System.Reflection;

namespace RealEarth
{
    /// <summary>
    /// F1 console: <c>reheight</c> — print engine Y (what the game map shows) vs
    /// height-mod true meters / int gameY (Everest-scale path).
    ///
    /// Stock columns top out ~250–255 blocks (= meters on the HUD). That is expected
    /// for Baked DTM / vanilla storage. Height mod can still report 8949 for Everest (sea 100).
    /// </summary>
    public class ConsoleCmdReHeight : ConsoleCmdAbstract
    {
        public override string[] getCommands() => new[] { "reheight", "re_height", "rh" };

        public override string getDescription() =>
            "RealEarth height-mod readout: engine Y vs true elev_m / mod gameY";

        public override string getHelp() =>
            "reheight           sample under local player\n" +
            "reheight <x> <z>  sample at world XZ (local host coords)\n" +
            "Note: map/HUD elevation is engine block Y (stock max ~250). " +
            "Height mod true meters live in .rte + EngineHeightMod.";

        public override void Execute(List<string> _params, CommandSenderInfo _senderInfo)
        {
            try
            {
                int x, z;
                int engineY = -1;
                if (_params != null && _params.Count >= 2
                    && int.TryParse(_params[0], out x) && int.TryParse(_params[1], out z))
                {
                    // explicit coords
                }
                else if (!TryGetLocalPlayerBlock(out x, out engineY, out z))
                {
                    SingletonMonoBehaviour<SdtdConsole>.Instance?.Output(
                        "[RealEarth] reheight: no local player (join a world first)");
                    return;
                }

                if (engineY < 0)
                    TryGetLocalPlayerBlock(out _, out engineY, out _);

                float elevM = float.NaN;
                int modY = -1;
                string mode = ModApi.Config?.MapMode ?? "?";
                bool streamed = ModApi.Session != null && ModApi.Session.IsStreamed;

                if (EngineHeight.EngineHeightMod.Active)
                {
                    modY = EngineHeight.EngineHeightMod.SampleGameHeightInt(x, z);
                    if (EngineHeight.EngineHeightMod.Store.TryGetSurfaceMeters(x, z, out float cached))
                        elevM = cached;
                }

                // Prefer live .rte sample when streamer has tiles (do not stomp MP focus 0).
                if (ModApi.Session != null && ModApi.Streamer != null)
                {
                    ModApi.Session.LocalToEarth(x, z, out int ex, out int ez);
                    // Console diagnostic: sync-load so sample is present (no focus stomp).
                    ModApi.Streamer.EnsureHotAround(ex, ez, radius: 1, allowSyncLoad: true);
                    if (ModApi.Streamer.TrySample(ex, ez, out float em, out byte lc, out _))
                    {
                        elevM = em;
                        if (EngineHeight.EngineHeightMod.Policy != null)
                            modY = EngineHeight.EngineHeightMod.Policy.MapMetersToGameY(em);
                        else if (modY < 0)
                        {
                            int sea = ModApi.Config?.SeaLevelGameY ?? 100;
                            modY = HeightCompress.MetersToGameYOneToOne(
                                em, sea, HeightCompress.EngineTargetMaxY);
                        }
                        Out(
                            $"[RealEarth] pos=({x},{engineY},{z}) mode={mode} streamed={streamed}");
                        Out(
                            "[RealEarth] NO COMPRESSION: gameY = seaLevelY + elev_m (1 m = 1 block)");
                        Out(
                            $"[RealEarth] elev_m={elevM:0.#} → heightMod gameY={modY}  " +
                            $"(ceiling={EngineHeight.EngineHeightMod.Policy?.MaxGameY ?? HeightCompress.EngineTargetMaxY})");
                        Out(
                            $"[RealEarth] engineY={engineY}  expanded={EngineHeight.EngineHeightMod.EngineExpanded} " +
                            $"allocMaxY={EngineHeight.EngineHeightMod.AllocatableColumnMaxY}");
                        Out(
                            $"[RealEarth] landcover={lc} earth=({ex},{ez}) " +
                            $"hotTiles={ModApi.Streamer.HotTileCount}");
                        if (!EngineHeight.EngineHeightMod.EngineExpanded && modY > 255)
                            Out(
                                "[RealEarth] YDim expand not applied: run Mods/RealEarth/Tools/apply_engine_expand.sh " +
                                "(or make engine-expand), then restart.");
                        return;
                    }
                }

                Out($"[RealEarth] pos=({x},{engineY},{z}) mode={mode} streamed={streamed}");
                Out($"[RealEarth] engineY={engineY}  (HUD/map ≈ this, stock max ~250)");
                if (!float.IsNaN(elevM))
                    Out($"[RealEarth] cached elev_m={elevM:0.#} heightMod gameY={modY}");
                else
                    Out("[RealEarth] no .rte sample here (Baked DTM only, or tiles not loaded).");
                if (!streamed)
                    Out(
                        "[RealEarth] HeightTest Baked world intentionally tops ~250 game Y " +
                        "(= +250m on the map). Pack peak is still 8849 m for the height mod.");
            }
            catch (Exception ex)
            {
                Out($"[RealEarth] reheight error: {ex.Message}");
            }
        }

        static void Out(string msg)
        {
            try
            {
                var cons = SingletonMonoBehaviour<SdtdConsole>.Instance;
                if (cons != null)
                {
                    cons.Output(msg);
                    return;
                }
            }
            catch { /* fall through */ }
            ModApi.Log(msg);
        }

        static bool TryGetLocalPlayerBlock(out int x, out int y, out int z)
        {
            x = y = z = 0;
            try
            {
                var gm = GameManager.Instance;
                if (gm == null) return false;
                var world = gm.World;
                if (world == null) return false;
                // Primary player
                EntityPlayerLocal? local = null;
                try
                {
                    local = world.GetPrimaryPlayer() as EntityPlayerLocal;
                }
                catch { /* ignore */ }
                if (local == null)
                {
                    var players = world.Players?.list;
                    if (players != null)
                    {
                        foreach (var p in players)
                        {
                            if (p is EntityPlayerLocal epl)
                            {
                                local = epl;
                                break;
                            }
                        }
                    }
                }
                if (local == null) return false;
                var pos = local.position;
                x = (int)Math.Floor(pos.x);
                y = (int)Math.Floor(pos.y);
                z = (int)Math.Floor(pos.z);
                return true;
            }
            catch
            {
                return false;
            }
        }
    }
}
