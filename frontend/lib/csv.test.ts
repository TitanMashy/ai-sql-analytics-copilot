import { describe, expect, it } from "vitest";

import { csvFilename, toCsv } from "@/lib/csv";

describe("toCsv", () => {
  it("writes a header, rows in column order, and CRLF line endings", () => {
    const csv = toCsv(["name", "total"], [{ total: 5, name: "Acme" }, { name: "Globex", total: 7.5 }]);

    expect(csv).toBe("name,total\r\nAcme,5\r\nGlobex,7.5\r\n");
  });

  it("quotes cells containing commas, quotes, or newlines", () => {
    const csv = toCsv(["note"], [{ note: 'He said "hi", twice' }, { note: "two\nlines" }]);

    expect(csv).toBe('note\r\n"He said ""hi"", twice"\r\n"two\nlines"\r\n');
  });

  it("renders null and undefined as empty cells and keeps zero", () => {
    expect(toCsv(["a", "b", "c"], [{ a: null, b: 0 }])).toBe("a,b,c\r\n,0,\r\n");
  });

  it.each(["=SUM(A1:A9)", "+1+1", "-2+3", "@cmd", "\tindent", "\rreturn"])(
    "neutralizes spreadsheet formulas such as %j",
    (value) => {
      const [, line] = toCsv(["v"], [{ v: value }]).split("\r\n");

      expect(line.replace(/^"/, "")).toMatch(/^'/);
    },
  );

  it("does not alter negative numbers, which are numbers and not formulas", () => {
    expect(toCsv(["v"], [{ v: -4.5 }])).toBe("v\r\n-4.5\r\n");
  });

  it("neutralizes formulas in column headers too", () => {
    expect(toCsv(["=HYPERLINK(\"x\")"], [])).toContain("'=HYPERLINK");
  });
});

describe("csvFilename", () => {
  it("builds a safe, dated file name from the chart title", () => {
    const name = csvFilename("Total Revenue by Company Name!", new Date("2026-10-06T12:00:00Z"));

    expect(name).toBe("total-revenue-by-company-name-2026-10-06.csv");
  });

  it("falls back to a generic name for titles with no usable characters", () => {
    expect(csvFilename("???", new Date("2026-10-06T00:00:00Z"))).toBe("analytics-result-2026-10-06.csv");
  });

  it("bounds the length of long titles", () => {
    const name = csvFilename("a".repeat(500), new Date("2026-10-06T00:00:00Z"));

    expect(name.length).toBeLessThanOrEqual(60 + "-2026-10-06.csv".length);
  });
});
