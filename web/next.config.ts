import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Hostnames (besides localhost) allowed to load dev-only assets, such as a tunnel. Without
  // them the page never hydrates and forms fall back to a plain browser submit.
  allowedDevOrigins: (process.env.ALLOWED_DEV_ORIGINS ?? "")
    .split(",")
    .map((host) => host.trim())
    .filter(Boolean),
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
