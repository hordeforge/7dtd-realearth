using System;

namespace RealEarth
{
    /// <summary>
    /// Local player block position for console diagnostics. One copy so the
    /// rll / reheight probes cannot drift on the player fallback.
    /// </summary>
    public static class LocalPlayerBlocks
    {
        /// <summary>
        /// Floor of the primary local player's position. Falls back to the first
        /// EntityPlayerLocal in the world when GetPrimaryPlayer is unavailable
        /// (dedicated / older signature). False when no local player is loaded.
        /// </summary>
        public static bool TryGet(out int x, out int y, out int z)
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
                catch { /* signature differs; use the list fallback */ }
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
