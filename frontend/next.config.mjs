/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Emit a minimal self-contained server bundle (.next/standalone) for a lean prod image.
  // Gated on an env var: the standalone copy step uses symlinks that fail on Windows dev
  // (EPERM) - the Docker build sets NEXT_OUTPUT=standalone; local `pnpm build` stays plain.
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
  env: {
    // Browser-facing base for DIRECT client calls (e.g. split-origin SSE). Leave EMPTY for
    // container / single-origin deploys so the browser uses the same-origin /api/alberto proxy.
    NEXT_PUBLIC_ALBERTO_API_URL: process.env.NEXT_PUBLIC_ALBERTO_API_URL || process.env.NEXT_PUBLIC_FORGE_API_URL || "",
    NEXT_PUBLIC_FORGE_API_URL: process.env.NEXT_PUBLIC_ALBERTO_API_URL || process.env.NEXT_PUBLIC_FORGE_API_URL || "",
  },
  async rewrites() {
    // Server-side proxy target, baked at BUILD time for standalone output.
    const api = process.env.ALBERTO_API_URL || process.env.FORGE_API_URL || "http://127.0.0.1:8000";
    return [
      { source: "/api/alberto/:path*", destination: `${api}/:path*` },
      { source: "/api/forge/:path*", destination: `${api}/:path*` },
    ];
  },
};
export default nextConfig;
