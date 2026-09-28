using System;

namespace RealEarth
{
    /// <summary>
    /// Shared output and local-player lookup for the F1 <c>re*</c> console commands.
    /// </summary>
    internal static class ConsoleOut
    {
        /// <summary>Print to the in-game console, falling back to the log when it is not up yet.</summary>
        internal static void Out(string msg)
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
            ModLog.Log(msg);
        }

        /// <summary>Block coords of the primary local player, or false when there is none.</summary>
        internal static bool TryGetLocalPlayerBlock(out int x, out int y, out int z)
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
