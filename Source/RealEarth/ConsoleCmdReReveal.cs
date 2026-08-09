using System;
using System.Collections.Generic;

namespace RealEarth
{
    /// <summary>F1: re-run debug map FOW uncover (full host + wide radius).</summary>
    public class ConsoleCmdReReveal : ConsoleCmdAbstract
    {
        public override string[] getCommands() => new[] { "rereveal", "re_reveal", "re_map" };

        public override string getDescription() =>
            "RealEarth debug: uncover wide map FOW (DebugRevealFullMap / radius)";

        public override string getHelp() =>
            "rereveal     reset and re-fill FOW for full host + radius around you\n" +
            "Requires DebugRevealFullMap and/or DebugMapRevealRadiusChunks > 0 in realearth.json.";

        public override void Execute(List<string> _params, CommandSenderInfo _senderInfo)
        {
            MapReveal.Reset();
            int x = 0, z = 0;
            bool have = TryLocal(out x, out z);
            if (have)
                MapReveal.TryRevealIfConfigured(x, z);
            else
                MapReveal.TryRevealIfConfigured();
            SingletonMonoBehaviour<SdtdConsole>.Instance?.Output(
                "[RealEarth] rereveal: FOW refresh requested " +
                $"(full={ModApi.Config?.DebugRevealFullMap} radiusChunks={ModApi.Config?.DebugMapRevealRadiusChunks}). " +
                "Check log for MapReveal lines.");
        }

        static bool TryLocal(out int x, out int z)
        {
            x = z = 0;
            try
            {
                var gm = GameManager.Instance;
                var world = gm?.World;
                var p = world?.GetPrimaryPlayer();
                if (p == null) return false;
                var pos = p.GetPosition();
                x = (int)Math.Floor(pos.x);
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
