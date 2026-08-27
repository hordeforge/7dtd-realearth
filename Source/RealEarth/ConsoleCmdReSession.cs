using System;
using System.Collections.Generic;
using System.IO;

namespace RealEarth
{
    /// <summary>F1: P4 absolute session snapshot dump/restore (offline-format realearth.session.v1).</summary>
    public class ConsoleCmdReSession : ConsoleCmdAbstract
    {
        public override string[] getCommands() => new[] { "resession", "re_session" };

        public override string getDescription() =>
            "RealEarth: dump/restore absolute session snapshot (origin + absolute Earth)";

        public override string getHelp() =>
            "resession              print current session snapshot JSON\n" +
            "resession save [path]  write snapshot (default: world save dir, else Config/)\n" +
            "resession load [path]  apply snapshot to session origin/absolute";

        public override void Execute(List<string> _params, CommandSenderInfo _senderInfo)
        {
            string sub = (_params != null && _params.Count > 0) ? _params[0].ToLowerInvariant() : "status";
            string path = (_params != null && _params.Count > 1)
                ? _params[1]
                : WorldSavePath.SessionPath();

            if (ModApi.Session == null)
            {
                Out("[RealEarth] resession: no session");
                return;
            }

            if (sub == "save")
            {
                // Dual-write via SessionStateStore (save dir + mod Config) unless explicit path.
                bool ok = (_params != null && _params.Count > 1)
                    ? SessionStateStore.TrySave(ModApi.Session, ModApi.Config, path)
                    : SessionStateStore.TrySave(ModApi.Session, ModApi.Config);
                var snap = SessionStateStore.Capture(ModApi.Session, ModApi.Config);
                if (ok)
                {
                    Out($"[RealEarth] resession saved → {WorldSavePath.SessionPath()} (+ Config fallback)");
                    Out(snap.ToJson());
                }
                else
                    Out("[RealEarth] resession save failed");
                return;
            }

            if (sub == "load")
            {
                try
                {
                    bool ok = (_params != null && _params.Count > 1)
                        ? SessionStateStore.TryLoad(ModApi.Session, path)
                        : SessionStateStore.TryLoad(ModApi.Session);
                    if (!ok)
                    {
                        Out("[RealEarth] resession load: missing or parse/apply failed");
                        return;
                    }
                    var snap = SessionStateStore.Capture(ModApi.Session, ModApi.Config);
                    Out(
                        $"[RealEarth] resession loaded absolute=({snap.AbsoluteX},{snap.AbsoluteZ}) " +
                        $"origin=({snap.OriginEarthX},{snap.OriginEarthZ}) mode={snap.MultiplayerOriginMode}");
                }
                catch (Exception ex)
                {
                    Out("[RealEarth] resession load failed: " + ex.GetType().Name + ": " + ex.Message);
                }
                return;
            }

            var cur = SessionStateStore.Capture(ModApi.Session, ModApi.Config);
            Out("[RealEarth] " + cur.ToJson());
            Out(
                $"  allowSlide={SessionOriginPolicy.AllowOriginSlide(cur.MultiplayerOriginMode, ModApi.Config?.LocalWindowSize ?? 1024, ModApi.Config?.WorldWidth ?? 0, ModApi.Config?.WorldHeight ?? 0, 1)}");
        }

        static void Out(string s) =>
            SingletonMonoBehaviour<SdtdConsole>.Instance?.Output(s);
    }
}
