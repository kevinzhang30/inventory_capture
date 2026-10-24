import { describe, expect, it } from "vitest";
import { parsePartsQuery, toSearchParams, toggle } from "./query";

describe("search query state", () => {
  it("round-trips through URLSearchParams", () => {
    const state = { q: "bolt", category: ["fasteners", "motion"], supplier: [], site: ["DAL1"], page: 3 };
    const parsed = parsePartsQuery(toSearchParams(state));
    expect(parsed).toEqual(state);
  });
  it("omits defaults", () => {
    expect(toSearchParams({ q: "", page: 1, category: [] }).toString()).toBe("");
  });
  it("guards bad page numbers", () => {
    expect(parsePartsQuery(new URLSearchParams("page=-4")).page).toBe(1);
  });
  it("toggles facet values", () => {
    expect(toggle(["a"], "b")).toEqual(["a", "b"]);
    expect(toggle(["a", "b"], "a")).toEqual(["b"]);
  });
});
