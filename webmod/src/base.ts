// Constants that tie the bundle to the mod's WebMod registration.
//
// The stock dedicated webserver maps <Mod.Path>/WebMod to
// /webmods/<ModInfo Name>/ (Webserver.WebMod.ctor), and the dashboard loads
// that bundle from window[<ModInfo Name>]. The name in ModInfo.xml and
// MOD_BASE_URL must stay in sync: changing one without the other breaks both
// the asset URLs and the dashboard registration.

export const MOD_BASE_URL = "/webmods/RealEarth/";

// Relative (to MOD_BASE_URL) path of the demo pack, matching the output of
// `make webmod-export`. Real packs follow the same data/<name> layout.
export const DEFAULT_PACK_PATH = "data/demo";
