import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Hostnames (besides localhost) allowed to load dev-only assets, such as a tunnel. Without
  // them the page never hydrates and forms fall back to a plain browser submit.
  allowedDevOrigins: (process.env.ALLOWED_DEV_ORIGINS ?? "")
    .split(",")
    .map((host) => host.trim())
    .filter(Boolean),
  poweredByHeader: false,
  // Baseline headers on every response. Not Content-Security-Policy: document files carry
  // their own (sandbox), forwarded by the BFF, and a global one here could replace it.
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          // Only our own pages may frame these (clickjacking).
          { key: "X-Frame-Options", value: "SAMEORIGIN" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
          // Browsers ignore it over plain HTTP (localhost); over HTTPS it keeps them on HTTPS.
          { key: "Strict-Transport-Security", value: "max-age=31536000" },
        ],
      },
    ];
  },
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
