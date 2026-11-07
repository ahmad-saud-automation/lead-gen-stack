/** @type {import('next').NextConfig} */
const api = (process.env.API_BASE ?? "http://127.0.0.1:8771").replace(/\/$/, "");

const nextConfig = {
  env: {
    // Python's address, used by server components only. The browser never sees it.
    API_BASE: api,
  },

  // Two Windows profiles share this folder. A second dev server sharing `.next` with one left
  // running by the other profile dies with `__webpack_modules__[moduleId] is not a function`.
  // NEXT_DIST_DIR gives an instance its own build output. Unset in normal use.
  distDir: process.env.NEXT_DIST_DIR || ".next",

  /* The browser asks THIS address for everything; Python's own pages are passed through.
   *
   *   /api/*          the engine
   *   /legacy         the V1 interface, the fallback if anything here misbehaves
   *   /style.css,
   *   /app.js         V1's two files
   *
   * Nothing in browser code knows Python's port, so there is no cross-origin rule to get
   * wrong. None of these paths collide with Next's own, which all live under /_next. */
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${api}/api/:path*` },
      { source: "/legacy", destination: `${api}/legacy` },
      { source: "/style.css", destination: `${api}/style.css` },
      { source: "/app.js", destination: `${api}/app.js` },
    ];
  },
};
export default nextConfig;
