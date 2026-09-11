using System;
using System.Collections.Generic;

namespace RealEarth
{
    /// <summary>
    /// F1 console: <c>relonlat</c> prints Earth lon/lat for the local player
    /// (or explicit local XZ). Soft gap 31 / LON_LAT debug surface.
    /// </summary>
    public class ConsoleCmdReLonLat : ConsoleCmdAbstract
    {
        public override string[] getCommands() => new[] { "relonlat", "re_lonlat", "rll" };

        public override string getDescription() =>
            "RealEarth lon/lat readout: local XZ → Earth blocks → lon/lat degrees";

        public override string getHelp() =>
            "relonlat           sample under local player\n" +
            "relonlat <x> <z>  sample at world XZ (local host coords)\n" +
            "Requires a streamed session with origin + pack coords.";

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
                    Out("[RealEarth] relonlat: no local player (join a world first)");
                    return;
                }

                var session = ModApi.Session;
                if (session == null || !session.IsStreamed)
                {
                    Out("[RealEarth] relonlat: no streamed session (load a Streamed pack first)");
                    return;
                }

                session.LocalToEarth(x, z, out int earthX, out int earthZ);
                session.EarthToLonLat(earthX, earthZ, out double lon, out double lat);

                int sea = ModApi.Config?.SeaLevelGameY ?? HeightInjectMath.DefaultSeaLevelGameY;
                int elevM = engineY >= 0
                    ? AltitudeClimate.ElevMFromGameY(engineY, sea)
                    : 0;

                Out(
                    $"[RealEarth] local=({x},{z}) earth=({earthX},{earthZ}) " +
                    $"lon={lon:0.######} lat={lat:0.######}");
                if (engineY >= 0)
                {
                    Out(
                        $"[RealEarth] gameY={engineY} elev_m≈{elevM} " +
                        $"(sea={sea}; hypoxia band={AltitudeClimate.HypoxiaBand(elevM)})");
                }
                Out(
                    $"[RealEarth] origin=({session.OriginEarthX},{session.OriginEarthZ})");
            }
            catch (Exception ex)
            {
                Out($"[RealEarth] relonlat error: {ex.GetType().Name}: {ex.Message}");
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
