using System;
using System.Reflection;

namespace RealEarth
{
    /// <summary>
    /// Probes for 0Harmony; all real patching is RuntimeHooks.Apply (reflection Harmony).
    /// </summary>
    public static class HarmonyBootstrap
    {
        public static void TryPatch()
        {
            try
            {
                var harmonyType = Type.GetType("HarmonyLib.Harmony, 0Harmony");
                if (harmonyType == null)
                {
                    // 0Harmony may load after mods; RuntimeHooks will retry discovery
                    ModApi.Log(
                        "HarmonyBootstrap: 0Harmony type not yet visible; " +
                        "RuntimeHooks.Apply will scan assemblies and attach patches.");
                    return;
                }

                ModApi.Log(
                    "HarmonyBootstrap: Harmony present, RuntimeHooks.Apply attaches single-map patches.");
            }
            catch (Exception ex)
            {
                ModApi.LogWarning($"HarmonyBootstrap: {ex.GetType().Name}: {ex.Message}");
            }
        }
    }
}
