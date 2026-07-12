// Centralized brand constants for XDIRGA METASCAN.
// Do not scatter hardcoded branding strings — always import from here.

export const PRODUCT_BRAND = {
  name: "XDIRGA METASCAN",
  shortName: "MetaScan",
  category: "Professional Trading Cockpit",
  descriptor: "Local-First Professional Trading System",
  tagline: "Monitor. Control. Protect.",
  runtimeName: "XDirga Runtime V4",
  productId: "xdirga-metascan",
  runtimeProtocolId: "xdirga-runtime-v4",
} as const;

export type BrandKey = keyof typeof PRODUCT_BRAND;

/** Suffix for browser tab titles: `${page} | XDIRGA METASCAN` */
export const pageTitle = (page: string) => `${page} | ${PRODUCT_BRAND.name}`;

/** Root document title, used in <head>. */
export const ROOT_TITLE = `${PRODUCT_BRAND.name} — ${PRODUCT_BRAND.category}`;
