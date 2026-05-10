import { describe, it, expect } from "vitest";
import { formatMoney, formatPercent, variancePct, formatDate } from "./format";

describe("formatMoney", () => {
  it("formats small values with grouped digits", () => {
    expect(formatMoney(123456)).toMatch(/123\s?456 ₽/);
  });
  it("formats compact millions", () => {
    expect(formatMoney(82_000_000, { compact: true })).toBe("82M ₽");
  });
  it("formats compact millions with one decimal", () => {
    expect(formatMoney(55_500_000, { compact: true })).toBe("55.5M ₽");
  });
  it("treats invalid as zero", () => {
    expect(formatMoney(NaN)).toMatch(/0 ₽/);
  });
});

describe("formatPercent", () => {
  it("renders integers by default", () => {
    expect(formatPercent(67)).toBe("67%");
  });
  it("renders dash when invalid", () => {
    expect(formatPercent(NaN)).toBe("—");
  });
});

describe("variancePct", () => {
  it("returns positive when actual exceeds plan", () => {
    expect(variancePct(100, 121)).toBeCloseTo(21);
  });
  it("returns negative when actual is below plan", () => {
    expect(variancePct(100, 90)).toBeCloseTo(-10);
  });
  it("returns 0 when plan is 0", () => {
    expect(variancePct(0, 50)).toBe(0);
  });
});

describe("formatDate", () => {
  it("renders dash for null", () => {
    expect(formatDate(null)).toBe("—");
  });
  it("returns input when not parseable", () => {
    expect(formatDate("not-a-date")).toBe("not-a-date");
  });
});
