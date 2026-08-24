using System.Collections.Generic;

namespace RealEarth
{
    /// <summary>F1: city map-label debug (discover-on-approach).</summary>
    public class ConsoleCmdReCities : ConsoleCmdAbstract
    {
        public override string[] getCommands() => new[] { "recities", "re_cities", "re_mapcities" };

        public override string getDescription() =>
            "RealEarth: city map labels (discover at city edge, pin at center)";

        public override string getHelp() =>
            "recities           status: catalog size / discovered\n" +
            "recities reset     clear discoveries and remove map pins\n" +
            "recities here      force-discover nearest place (debug)\n" +
            "Names unlock when you reach a city's edge; the pin is always at the city center.";

        public override void Execute(List<string> _params, CommandSenderInfo _senderInfo)
        {
            string sub = (_params != null && _params.Count > 0) ? _params[0].ToLowerInvariant() : "status";
            if (sub == "reset")
            {
                CityMapLabels.Reset();
                Out("[RealEarth] recities: discoveries cleared.");
                return;
            }

            if (sub == "here")
            {
                // Force tick at player; if still none, temporarily huge scale
                try
                {
                    var gm = GameManager.Instance;
                    var p = gm?.World?.GetPrimaryPlayer();
                    if (p == null)
                    {
                        Out("[RealEarth] recities here: no local player.");
                        return;
                    }
                    var pos = p.GetPosition();
                    float old = ModApi.Config?.CityMapDiscoverRadiusScale ?? 1f;
                    if (ModApi.Config != null)
                        ModApi.Config.CityMapDiscoverRadiusScale = 50f;
                    // force=true bypasses the shared tick throttle (command must
                    // always run a real discovery pass, not decrement the counter).
                    CityMapLabels.TickPlayer((int)System.Math.Floor(pos.x), (int)System.Math.Floor(pos.z), force: true);
                    if (ModApi.Config != null)
                        ModApi.Config.CityMapDiscoverRadiusScale = old;
                    Out("[RealEarth] recities here: discovery pass with temporary large radius.");
                }
                catch (System.Exception ex)
                {
                    Out("[RealEarth] recities here failed: " + ex.Message);
                }
                return;
            }

            CityMapLabels.TryPlaceIfConfigured();
            Out($"[RealEarth] recities: catalog={CityMapLabels.CatalogCount} " +
                $"discovered={CityMapLabels.DiscoveredCount} " +
                $"(approach city edge → name pins at center).");
            Out($"  ShowCityNamesOnMap={ModApi.Config?.ShowCityNamesOnMap} " +
                $"scale={ModApi.Config?.CityMapDiscoverRadiusScale}");
        }

        static void Out(string s) =>
            SingletonMonoBehaviour<SdtdConsole>.Instance?.Output(s);
    }
}
