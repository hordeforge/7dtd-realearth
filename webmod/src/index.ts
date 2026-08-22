// Webmod entry point.
//
// The stock dashboard loads <ModName>/bundle.js from the mod's WebMod folder
// and reads window[<ModName>] after it runs (Webserver.WebMod.ctor +
// dashboard /api/mods integration, see webmod/README.md). This file publishes
// that object: routes become left-sidebar menu items (mods/realearth/<route>)
// and settings become sidebar Settings sections. Components must use the
// React injected via props, never a bundled copy, so this bundle carries no
// react dependency.

import { MapPage } from "./map-page";
import { OverviewPage } from "./overview";
import { RealEarthSettings } from "./settings";
import type { WebModExports } from "./types";

const realEarthWebMod: WebModExports = {
  routes: {
    Overview: OverviewPage,
    Map: MapPage,
  },
  settings: {
    RealEarth: RealEarthSettings,
  },
};

globalThis.RealEarth = realEarthWebMod;
