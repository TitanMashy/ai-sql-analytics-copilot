import type { NextConfig } from "next";

/**
 * The only backend routes the browser may reach through the same-origin proxy.
 *
 * Everything else under /api (direct SQL, SQL validation, metrics, raw schema, SQL generation
 * without execution) stays unreachable from the browser: it returns 404 from this origin.
 * Add a route here only when the UI needs it.
 */
export const proxiedRoutes = [
  "/api/v1/analytics/ask",
  "/api/v1/analytics/conversations",
  "/api/v1/analytics/conversations/:conversationId",
  "/api/v1/analytics/conversations/:conversationId/turns",
  "/api/v1/schema/tables",
  "/api/v1/schema/tables/:tableName",
  "/api/v1/health",
  "/api/v1/health/ready",
] as const;

const isProduction = process.env.NODE_ENV === "production";

// How long the proxy waits for the backend. It must match the browser's timeout (lib/api.ts), or
// the proxy would give up at its 30-second default first.
const requestTimeoutMs = Number(process.env.NEXT_PUBLIC_REQUEST_TIMEOUT_MS) || 30_000;

// Next.js emits inline bootstrap scripts, so script-src needs 'unsafe-inline'; development
// additionally needs 'unsafe-eval' for React's debugging tooling.
const contentSecurityPolicy = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isProduction ? "" : " 'unsafe-eval'"}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  "connect-src 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

export const securityHeaders = [
  { key: "Content-Security-Policy", value: contentSecurityPolicy },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
  ...(isProduction
    ? [{ key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" }]
    : []),
];

const nextConfig: NextConfig = {
  reactCompiler: true,
  output: "standalone",
  experimental: { proxyTimeout: requestTimeoutMs },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
  async rewrites() {
    const backendUrl = process.env.INTERNAL_API_URL ?? "http://localhost:8000";
    return proxiedRoutes.map((source) => ({
      source,
      destination: `${backendUrl}${source}`,
    }));
  },
};

export default nextConfig;
