import { describe, expect, it } from "vitest";
import { confidenceLevel, pct } from "./confidence";

describe("confidenceLevel", () => {
  it("buckets by threshold", () => {
    expect(confidenceLevel(0.5)).toBe("low");
    expect(confidenceLevel(0.7)).toBe("medium");
    expect(confidenceLevel(0.849)).toBe("medium");
    expect(confidenceLevel(0.85)).toBe("high");
    expect(confidenceLevel(null)).toBe("unknown");
  });
  it("formats percentages", () => {
    expect(pct(0.9123)).toBe("91.2%");
    expect(pct(null)).toBe("—");
  });
});
