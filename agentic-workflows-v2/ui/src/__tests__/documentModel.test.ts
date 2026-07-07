import { describe, expect, it } from "vitest";
import {
  addDependency,
  addStep,
  cloneDocument,
  deriveGraph,
  documentsEqual,
  edgeInfo,
  getStep,
  getSteps,
  nextStepName,
  patchStep,
  patchStepInput,
  removeDependency,
  removeStep,
} from "../components/editor/documentModel";

function doc(): Record<string, unknown> {
  return {
    name: "wf",
    steps: [
      {
        name: "analyze",
        agent: "tier1_analyzer",
        depends_on: [],
        inputs: {},
        outputs: { report: "report_ctx" },
      },
      {
        name: "review",
        agent: "tier2_reviewer",
        depends_on: ["analyze"],
        inputs: { report: "${steps.analyze.outputs.report}" },
        when: "inputs.ready",
      },
    ],
  };
}

describe("documentModel", () => {
  it("getSteps filters non-mapping entries", () => {
    const document = { steps: [{ name: "a" }, "junk", null] };
    expect(getSteps(document)).toEqual([{ name: "a" }]);
    expect(getSteps({})).toEqual([]);
  });

  it("patchStep merges values and deletes undefined keys without mutating", () => {
    const original = doc();
    const next = patchStep(original, "review", {
      persona: "winston_architect",
      when: undefined,
    });

    const patched = getStep(next, "review");
    expect(patched?.persona).toBe("winston_architect");
    expect(patched).not.toHaveProperty("when");
    // Original untouched (immutability contract).
    expect(getStep(original, "review")?.when).toBe("inputs.ready");
  });

  it("addStep appends a uniquely-named step depending on the anchor", () => {
    const { document, name } = addStep(doc(), "review");
    expect(name).toBe("step_3");
    const added = getStep(document, name);
    expect(added?.depends_on).toEqual(["review"]);
    expect(nextStepName(document)).toBe("step_4");
  });

  it("removeStep scrubs depends_on lists and dangling input references", () => {
    const next = removeStep(doc(), "analyze");
    expect(getStep(next, "analyze")).toBeNull();
    const review = getStep(next, "review");
    expect(review?.depends_on).toEqual([]);
    // The input mapping that read ${steps.analyze...} must not dangle.
    expect(review?.inputs).toEqual({});
  });

  it("removeStep keeps input entries that do not reference the removed step", () => {
    const document = patchStepInput(doc(), "review", "note", "static text");
    const review = getStep(removeStep(document, "analyze"), "review");
    expect(review?.inputs).toEqual({ note: "static text" });
  });

  it("addDependency ignores self-references and duplicates", () => {
    const withDep = addDependency(doc(), "review", "analyze");
    expect(getStep(withDep, "analyze")?.depends_on).toEqual(["review"]);

    const selfRef = addDependency(doc(), "review", "review");
    expect(getStep(selfRef, "review")?.depends_on).toEqual(["analyze"]);

    const duplicate = addDependency(doc(), "analyze", "review");
    expect(getStep(duplicate, "review")?.depends_on).toEqual(["analyze"]);
  });

  it("removeDependency severs the edge and its data mappings", () => {
    const next = removeDependency(doc(), "analyze", "review");
    const review = getStep(next, "review");
    expect(review?.depends_on).toEqual([]);
    expect(review?.inputs).toEqual({});
  });

  it("edgeInfo reports mappings and the target condition", () => {
    const info = edgeInfo(doc(), "analyze", "review");
    expect(info.mappings).toEqual([
      { key: "report", expression: "${steps.analyze.outputs.report}" },
    ]);
    expect(info.when).toBe("inputs.ready");
  });

  it("edgeInfo returns no mappings for ordering-only edges", () => {
    const document = patchStepInput(doc(), "review", "report", "static value");
    const info = edgeInfo(document, "analyze", "review");
    expect(info.mappings).toEqual([]);
  });

  it("patchStepInput updates a single expression", () => {
    const next = patchStepInput(
      doc(),
      "review",
      "report",
      "${steps.analyze.outputs.summary}"
    );
    const inputs = getStep(next, "review")?.inputs as Record<string, unknown>;
    expect(inputs.report).toBe("${steps.analyze.outputs.summary}");
  });

  it("deriveGraph builds labeled edges and config-aware nodes", () => {
    const document = patchStep(doc(), "review", {
      persona: "quinn_qa",
      model: "gh:openai/gpt-4o-mini",
    });
    const graph = deriveGraph(document);

    expect(graph.nodes.map((n) => n.id)).toEqual(["analyze", "review"]);
    const reviewNode = graph.nodes[1]!;
    expect(reviewNode.persona).toBe("quinn_qa");
    expect(reviewNode.model).toBe("gh:openai/gpt-4o-mini");

    expect(graph.edges).toHaveLength(1);
    const edge = graph.edges[0]!;
    expect(edge.id).toBe("analyze->review");
    expect(edge.label).toBe("report");
    expect(edge.mappings).toEqual([
      "report = ${steps.analyze.outputs.report}",
    ]);
    expect(edge.when).toBe("inputs.ready");
  });

  it("documentsEqual and cloneDocument respect structural identity", () => {
    const a = doc();
    const clone = cloneDocument(a);
    expect(documentsEqual(a, clone)).toBe(true);
    const changed = patchStep(a, "review", { persona: "x" });
    expect(documentsEqual(a, changed)).toBe(false);
  });
});
