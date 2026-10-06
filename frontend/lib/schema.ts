/**
 * Minimal runtime validators for API responses.
 *
 * Responses cross a trust boundary (network, proxy, a possibly newer or older backend), so the
 * client checks their shape before the UI relies on it. These combinators are deliberately tiny and
 * dependency-free; the field lists they enforce are the ones in `contracts/api-contract.json`,
 * which `types/contract.test.ts` and the backend's `tests/test_api_contract.py` keep in step with
 * the TypeScript types and the response models.
 */
export type Check = (value: unknown) => boolean;

export const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

export const isString: Check = (value) => typeof value === "string";
export const isBoolean: Check = (value) => typeof value === "boolean";
export const isFiniteNumber: Check = (value) => typeof value === "number" && Number.isFinite(value);
export const isNonNegativeNumber: Check = (value) =>
  typeof value === "number" && Number.isFinite(value) && value >= 0;

export const arrayOf = (check: Check): Check => (value) =>
  Array.isArray(value) && value.every(check);

export const stringArray: Check = arrayOf(isString);

export const oneOf = (...allowed: readonly string[]): Check => (value) =>
  typeof value === "string" && allowed.includes(value);

/** Accepts `undefined` and `null` as well as anything the inner check accepts. */
export const optional = (check: Check): Check => (value) =>
  value === undefined || value === null || check(value);

export const anyOf = (...checks: Check[]): Check => (value) => checks.some((check) => check(value));

export const isNull: Check = (value) => value === null;

/** An object whose listed fields pass their checks. Other fields are allowed and preserved. */
export const shape = (fields: Record<string, Check>): Check => (value) =>
  isRecord(value) && Object.entries(fields).every(([key, check]) => check(value[key]));
