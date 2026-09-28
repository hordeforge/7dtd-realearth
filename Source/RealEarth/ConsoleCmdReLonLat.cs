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
                int x = 0, z = 0;
                int engineY = -1;
                // TryParse assigns x/z on both outcomes, so either path leaves them set.
                bool explicitCoords = _params != null && _params.Count >= 2
                    && int.TryParse(_params[0], out x) && int.TryParse(_params[1], out z);
                if (!explicitCoords && !ConsoleOut.TryGetLocalPlayerBlock(out x, out engineY, out z))
                {
                    ConsoleOut.Out("[RealEarth] relonlat: no local player (join a world first)");
                    return;
                }

                var session = ModApi.Session;
                if (session == null || !session.IsStreamed)
                {
                    ConsoleOut.Out("[RealEarth] relonlat: no streamed session (load a Streamed pack first)");
                    return;
                }

                session.LocalToEarth(x, z, out int earthX, out int earthZ);
                session.EarthToLonLat(earthX, earthZ, out double lon, out double lat);

                int sea = ModApi.Config?.SeaLevelGameY ?? HeightInjectMath.DefaultSeaLevelGameY;
                int elevM = engineY >= 0
                    ? AltitudeClimate.ElevMFromGameY(engineY, sea)
                    : 0;

                ConsoleOut.Out(
                    $"[RealEarth] local=({x},{z}) earth=({earthX},{earthZ}) " +
                    $"lon={lon:0.######} lat={lat:0.######}");
                if (engineY >= 0)
                {
                    ConsoleOut.Out(
                        $"[RealEarth] gameY={engineY} elev_m≈{elevM} " +
                        $"(sea={sea}; hypoxia band={AltitudeClimate.HypoxiaBand(elevM)})");
                }
                ConsoleOut.Out(
                    $"[RealEarth] origin=({session.OriginEarthX},{session.OriginEarthZ})");
            }
            catch (Exception ex)
            {
                ConsoleOut.Out($"[RealEarth] relonlat error: {ex.GetType().Name}: {ex.Message}");
            }
        }
    }
}
