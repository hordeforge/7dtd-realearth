using System;
using System.IO;

namespace RealEarth
{
    /// <summary>
    /// Durable atomic file publish shared by the tile cache and session store.
    /// Contract: the live destination is never destroyed before its replacement
    /// is in place, and a failed temp write never orphans the .tmp.
    ///
    /// Sequence: write a unique temp, File.Replace (atomic where supported),
    /// then a backup-move fallback for filesystems without Replace: old → .bak,
    /// temp → path, delete .bak; a failed middle move restores the backup so the
    /// previous good copy always survives. (Deleting the destination first, as
    /// earlier fallbacks did, turned any Move failure into total data loss.)
    /// </summary>
    internal static class AtomicPublish
    {
        public static void WriteAllBytes(string path, byte[] bytes)
        {
            string tmp = TempPath(path);
            try
            {
                CreateTargetDir(path);
                File.WriteAllBytes(tmp, bytes);
            }
            catch
            {
                TryDeleteQuiet(tmp);
                throw;
            }
            SwapIntoPlace(tmp, path);
        }

        public static void WriteAllText(string path, string contents)
        {
            string tmp = TempPath(path);
            try
            {
                CreateTargetDir(path);
                File.WriteAllText(tmp, contents);
            }
            catch
            {
                TryDeleteQuiet(tmp);
                throw;
            }
            SwapIntoPlace(tmp, path);
        }

        static string TempPath(string path)
            => path + "." + Guid.NewGuid().ToString("N") + ".tmp";

        static void CreateTargetDir(string path)
        {
            string? dir = Path.GetDirectoryName(path);
            if (!string.IsNullOrEmpty(dir))
                Directory.CreateDirectory(dir);
        }

        /// <summary>Swap tmp into path; caller gave up ownership of tmp.</summary>
        static void SwapIntoPlace(string tmp, string path)
        {
            string? backup = null;
            try
            {
                if (File.Exists(path))
                {
                    try
                    {
                        File.Replace(tmp, path, null);
                        return;
                    }
                    catch
                    {
                        // Replace unsupported on this filesystem (some mounts,
                        // FAT volumes): fall through to the backup-move dance.
                    }

                    backup = path + "." + Guid.NewGuid().ToString("N") + ".re_bak";
                    File.Move(path, backup);
                    try
                    {
                        File.Move(tmp, path);
                    }
                    catch
                    {
                        // Replacement failed: put the original content back.
                        File.Move(backup, path);
                        backup = null;
                        throw;
                    }
                    return;
                }

                File.Move(tmp, path);
            }
            finally
            {
                if (backup != null)
                    TryDeleteQuiet(backup);
                TryDeleteQuiet(tmp);
            }
        }

        static void TryDeleteQuiet(string file)
        {
            try { if (File.Exists(file)) File.Delete(file); }
            catch { /* best effort: leftover temp must not mask the real error */ }
        }
    }
}
