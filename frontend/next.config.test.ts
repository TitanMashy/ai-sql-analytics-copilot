import { describe, expect, it } from "vitest";

import nextConfig, { proxiedRoutes, securityHeaders } from "./next.config";

type Rewrite = { source: string; destination: string };

function matches(source: string, path: string) {
  const pattern = source.replace(/:[A-Za-z]+/g, "[^/]+");
  return new RegExp(`^${pattern}$`).test(path);
}

async function rewrites() {
  const result = await nextConfig.rewrites!();
  return result as Rewrite[];
}

describe("same-origin API proxy", () => {
  it("forwards only the routes the UI needs", async () => {
    const sources = (await rewrites()).map((rewrite) => rewrite.source);

    expect(sources).toEqual([...proxiedRoutes]);
    expect(sources.some((source) => source.includes("*"))).toBe(false);
  });

  it.each([
    "/api/v1/analytics/query",
    "/api/v1/analytics/validate",
    "/api/v1/analytics/generate",
    "/api/v1/metrics",
    "/api/v1/schema",
    "/api/v1/analytics/ask/extra",
    "/api/v1/analytics/conversations/abc/other",
    "/api/v1/anything-else",
    "/docs",
    "/openapi.json",
  ])("does not forward %s", async (path) => {
    const sources = (await rewrites()).map((rewrite) => rewrite.source);

    expect(sources.some((source) => matches(source, path))).toBe(false);
  });

  it.each([
    "/api/v1/analytics/ask",
    "/api/v1/analytics/conversations",
    "/api/v1/analytics/conversations/3f2a/turns",
    "/api/v1/schema/tables",
    "/api/v1/health/ready",
  ])("forwards %s", async (path) => {
    const sources = (await rewrites()).map((rewrite) => rewrite.source);

    expect(sources.some((source) => matches(source, path))).toBe(true);
  });

  it("sends each route to the same path on the backend", async () => {
    for (const rewrite of await rewrites()) {
      expect(rewrite.destination.endsWith(rewrite.source)).toBe(true);
    }
  });
});

describe("security headers", () => {
  it("applies the headers to every page", async () => {
    const headers = await nextConfig.headers!();

    expect(headers).toHaveLength(1);
    expect(headers[0].source).toBe("/:path*");
    expect(headers[0].headers).toEqual(securityHeaders);
  });

  it("includes the required hardening headers", () => {
    const byKey = Object.fromEntries(securityHeaders.map((header) => [header.key, header.value]));

    expect(byKey["X-Frame-Options"]).toBe("DENY");
    expect(byKey["X-Content-Type-Options"]).toBe("nosniff");
    expect(byKey["Referrer-Policy"]).toBe("strict-origin-when-cross-origin");
    expect(byKey["Permissions-Policy"]).toContain("camera=()");
  });

  it("uses a restrictive content security policy", () => {
    const csp = securityHeaders.find((header) => header.key === "Content-Security-Policy")!.value;

    expect(csp).toContain("default-src 'self'");
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).toContain("object-src 'none'");
    expect(csp).toContain("connect-src 'self'");
    expect(csp).not.toMatch(/(^|;\s*)default-src[^;]*\*/);
  });
});
