// Global declarations for the webmod bundle.
//
// The stock dashboard registers a web mod by reading window[<ModInfo Name>]
// after loading its bundle (see webmod/README.md). index.ts publishes the
// WebModExports object there, so the Window interface is augmented and
// globalThis.RealEarth type-checks in the bundle.

import type { WebModExports } from "./types";

declare global {
  var RealEarth: WebModExports | undefined;
}
