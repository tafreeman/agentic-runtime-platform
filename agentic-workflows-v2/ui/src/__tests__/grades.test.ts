import { describe, it, expect } from "vitest";
import {
  scoreToPercent,
  gradeLetter,
  gradeColorClass,
  isPassingScore,
} from "../lib/grades";

describe("scoreToPercent", () => {
  it("normalizes 0..1 fractions to 0..100", () => {
    expect(scoreToPercent(0.87)).toBeCloseTo(87);
    expect(scoreToPercent(1)).toBe(100);
  });
  it("passes through 0..100 percentages without double-scaling", () => {
    expect(scoreToPercent(87)).toBe(87);
    expect(scoreToPercent(100)).toBe(100);
  });
  it("returns null for missing or NaN", () => {
    expect(scoreToPercent(null)).toBeNull();
    expect(scoreToPercent(undefined)).toBeNull();
    expect(scoreToPercent(Number.NaN)).toBeNull();
  });
});

describe("gradeLetter", () => {
  it("prefers the server-provided letter", () => {
    expect(gradeLetter("b", 0.99)).toBe("B");
  });
  it("treats an empty/whitespace grade as absent", () => {
    expect(gradeLetter("", 0.95)).toBe("A");
    expect(gradeLetter("  ", null)).toBeNull();
  });
  it("derives from a 0..1 score", () => {
    expect(gradeLetter(null, 0.95)).toBe("A");
    expect(gradeLetter(null, 0.5)).toBe("F");
  });
  it("derives from a 0..100 score without mis-grading everything A", () => {
    expect(gradeLetter(null, 95)).toBe("A");
    expect(gradeLetter(null, 65)).toBe("D");
    expect(gradeLetter(null, 40)).toBe("F");
  });
  it("returns null with neither grade nor score", () => {
    expect(gradeLetter(null, null)).toBeNull();
    expect(gradeLetter(undefined, undefined)).toBeNull();
  });
});

describe("gradeColorClass", () => {
  it("maps grades to colors and absence to faint", () => {
    expect(gradeColorClass("S")).toBe("text-b-green");
    expect(gradeColorClass("A")).toBe("text-b-green");
    expect(gradeColorClass("C")).toBe("text-b-amber");
    expect(gradeColorClass("F")).toBe("text-b-red");
    expect(gradeColorClass(null)).toBe("text-b-text-faint");
  });
});

describe("isPassingScore", () => {
  it("passes S/A/B grades and >=75 scores; fails below", () => {
    expect(isPassingScore("A", null)).toBe(true);
    expect(isPassingScore("D", null)).toBe(false);
    expect(isPassingScore(null, 0.8)).toBe(true);
    expect(isPassingScore(null, 0.7)).toBe(false);
    expect(isPassingScore(null, 80)).toBe(true);
    expect(isPassingScore(null, null)).toBe(false);
  });
});
