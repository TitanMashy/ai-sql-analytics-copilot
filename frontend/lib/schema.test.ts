import { describe, expect, it } from "vitest";

import {
  anyOf,
  arrayOf,
  isFiniteNumber,
  isNonNegativeNumber,
  isNull,
  isRecord,
  isString,
  oneOf,
  optional,
  shape,
  stringArray,
} from "@/lib/schema";

describe("response validators", () => {
  it("distinguishes records from arrays, null, and primitives", () => {
    expect(isRecord({})).toBe(true);
    expect(isRecord([])).toBe(false);
    expect(isRecord(null)).toBe(false);
    expect(isRecord("x")).toBe(false);
  });

  it("checks numbers strictly", () => {
    expect(isNonNegativeNumber(0)).toBe(true);
    expect(isNonNegativeNumber(-1)).toBe(false);
    expect(isNonNegativeNumber(Number.NaN)).toBe(false);
    expect(isNonNegativeNumber("1")).toBe(false);
    expect(isFiniteNumber(-5)).toBe(true);
    expect(isFiniteNumber(Number.POSITIVE_INFINITY)).toBe(false);
  });

  it("validates arrays element by element", () => {
    expect(stringArray(["a", "b"])).toBe(true);
    expect(stringArray(["a", 1])).toBe(false);
    expect(stringArray("a")).toBe(false);
    expect(arrayOf(isFiniteNumber)([])).toBe(true);
  });

  it("accepts only the listed values in oneOf", () => {
    const format = oneOf("bar", "line");

    expect(format("bar")).toBe(true);
    expect(format("pie")).toBe(false);
    expect(format(1)).toBe(false);
  });

  it("lets optional fields be missing or null but not wrong", () => {
    const check = optional(isString);

    expect(check(undefined)).toBe(true);
    expect(check(null)).toBe(true);
    expect(check("x")).toBe(true);
    expect(check(3)).toBe(false);
  });

  it("combines alternatives with anyOf", () => {
    const check = anyOf(isString, isFiniteNumber, isNull);

    expect([check("a"), check(2), check(null)]).toEqual([true, true, true]);
    expect(check({})).toBe(false);
  });

  it("requires every listed field in a shape and tolerates extras", () => {
    const check = shape({ id: isString, tags: stringArray, note: optional(isString) });

    expect(check({ id: "1", tags: [], extra: true })).toBe(true);
    expect(check({ id: "1", tags: [], note: null })).toBe(true);
    expect(check({ id: "1" })).toBe(false);
    expect(check({ id: 1, tags: [] })).toBe(false);
    expect(check(null)).toBe(false);
  });
});
