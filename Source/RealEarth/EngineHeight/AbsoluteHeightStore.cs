using System;
using System.Collections.Generic;

namespace RealEarth.EngineHeight
{
    /// <summary>
    /// Sparse absolute elevation authority for the engine-height path.
    /// Stores real meters ASL (from .rte) in Y-sections so future tall columns do not need a
    /// full static 0..Max slab in RAM — only sections that contain surface/build data.
    ///
    /// Cap + LRU eviction keeps long MP sessions bounded.
    /// </summary>
    public sealed class AbsoluteHeightStore
    {
        readonly int _sectionHeight;
        readonly int _maxColumns;
        readonly Dictionary<long, SectionColumn> _columns = new Dictionary<long, SectionColumn>();
        readonly LinkedList<long> _lru = new LinkedList<long>();
        readonly Dictionary<long, LinkedListNode<long>> _lruNodes = new Dictionary<long, LinkedListNode<long>>();
        readonly object _lock = new object();

        public AbsoluteHeightStore(int sectionHeight = 16, int maxColumns = 4096)
        {
            _sectionHeight = Math.Max(4, sectionHeight);
            _maxColumns = Math.Max(64, maxColumns);
        }

        public int SectionHeight => _sectionHeight;
        public int ColumnCount { get { lock (_lock) return _columns.Count; } }

        static long Key(int chunkX, int chunkZ) => ((long)chunkX << 32) ^ (uint)chunkZ;

        /// <summary>
        /// Store surface meters keyed by absolute Earth block XZ when a session is available
        /// (survives origin slide). Falls back to raw coords if no session.
        /// </summary>
        public void SetSurfaceMeters(int worldBlockX, int worldBlockZ, float elevM)
        {
            ToEarthKey(worldBlockX, worldBlockZ, out int ex, out int ez);
            int cx = EngineReflection.FloorDiv(ex, 16);
            int cz = EngineReflection.FloorDiv(ez, 16);
            int lx = SessionOriginPolicy.FoldCoord(ex, 16);
            int lz = SessionOriginPolicy.FoldCoord(ez, 16);
            long key = Key(cx, cz);
            lock (_lock)
            {
                if (!_columns.TryGetValue(key, out var col))
                {
                    col = new SectionColumn(_sectionHeight);
                    _columns[key] = col;
                    var node = _lru.AddFirst(key);
                    _lruNodes[key] = node;
                    EvictIfNeeded();
                }
                else
                {
                    TouchLru(key);
                }
                col.SetSurface(lx, lz, elevM);
            }
        }

        public bool TryGetSurfaceMeters(int worldBlockX, int worldBlockZ, out float elevM)
        {
            elevM = 0;
            ToEarthKey(worldBlockX, worldBlockZ, out int ex, out int ez);
            int cx = EngineReflection.FloorDiv(ex, 16);
            int cz = EngineReflection.FloorDiv(ez, 16);
            int lx = SessionOriginPolicy.FoldCoord(ex, 16);
            int lz = SessionOriginPolicy.FoldCoord(ez, 16);
            long key = Key(cx, cz);
            lock (_lock)
            {
                if (!_columns.TryGetValue(key, out var col))
                    return false;
                TouchLru(key);
                return col.TryGetSurface(lx, lz, out elevM);
            }
        }

        static void ToEarthKey(int worldBlockX, int worldBlockZ, out int ex, out int ez)
        {
            try
            {
                var session = ModApi.Session;
                if (session != null)
                {
                    session.LocalToEarth(worldBlockX, worldBlockZ, out ex, out ez);
                    return;
                }
            }
            catch { /* fall through */ }
            ex = worldBlockX;
            ez = worldBlockZ;
        }

        /// <summary>Section indices that should stay hot around a surface elevation (meters as future Y).</summary>
        public void GetHotSectionRange(float surfaceM, int digMargin, int buildMargin, out int minSection, out int maxSection)
        {
            // P8 scaffold: shared SparseYScaffold section math
            int surfaceY = (int)Math.Round(surfaceM);
            SparseYScaffold.HotSectionRange(
                surfaceY, digMargin, buildMargin, _sectionHeight,
                out minSection, out maxSection);
        }

        public void Clear()
        {
            lock (_lock)
            {
                _columns.Clear();
                _lru.Clear();
                _lruNodes.Clear();
            }
        }

        void TouchLru(long key)
        {
            // Hot path (every height sample in expanded mode): repeated samples of the
            // same/nearby columns hit an already-MRU node; skipping the remove/relink
            // keeps those touches to one dictionary lookup.
            if (_lruNodes.TryGetValue(key, out var node) && _lru.First != node)
            {
                _lru.Remove(node);
                _lru.AddFirst(node);
            }
        }

        void EvictIfNeeded()
        {
            while (_columns.Count > _maxColumns && _lru.Last != null)
            {
                long old = _lru.Last.Value;
                _lru.RemoveLast();
                _lruNodes.Remove(old);
                _columns.Remove(old);
            }
        }

        sealed class SectionColumn
        {
            readonly int _sectionHeight;
            // surface meters per local XZ (16x16); NaN = unset
            readonly float[] _surface = new float[256];

            public SectionColumn(int sectionHeight)
            {
                _sectionHeight = sectionHeight;
                for (int i = 0; i < _surface.Length; i++)
                    _surface[i] = float.NaN;
            }

            public void SetSurface(int lx, int lz, float elevM)
            {
                if ((uint)lx >= 16 || (uint)lz >= 16) return;
                _surface[lz * 16 + lx] = elevM;
            }

            public bool TryGetSurface(int lx, int lz, out float elevM)
            {
                elevM = 0;
                if ((uint)lx >= 16 || (uint)lz >= 16) return false;
                float v = _surface[lz * 16 + lx];
                if (float.IsNaN(v)) return false;
                elevM = v;
                return true;
            }
        }
    }
}
