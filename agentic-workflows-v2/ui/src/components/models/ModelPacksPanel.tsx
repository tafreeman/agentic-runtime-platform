import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Archive,
  CheckCircle2,
  Copy,
  Download,
  GitBranch,
  Plus,
  ShieldCheck,
  Upload,
} from "lucide-react";
import { toast } from "sonner";
import {
  activateModelPack,
  archiveModelPack,
  bindModelPack,
  clearModelPackBinding,
  createModelPack,
  duplicateModelPack,
  exportModelPack,
  getModelPackDependencies,
  importModelPack,
  listModelPacks,
  validateModelPack,
  versionModelPack,
} from "../../api/client";
import type {
  ModelPack,
  ModelPackCreateRequest,
  ModelPackRef,
  ModelPackUpdateRequest,
  ModelPackValidationResponse,
} from "../../api/types";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { Textarea } from "../ui/textarea";

interface EditorState {
  name: string;
  description: string;
  tierChains: string;
  allowedProviders: string;
  capabilities: string;
  judgeModel: string;
}

const EMPTY_EDITOR: EditorState = {
  name: "",
  description: "",
  tierChains: "{}",
  allowedProviders: "",
  capabilities: "{}",
  judgeModel: "",
};

function refKey(ref: ModelPackRef): string {
  return `${ref.id}@${ref.version}`;
}

function editorFor(pack: ModelPack): EditorState {
  return {
    name: pack.name,
    description: pack.description,
    tierChains: JSON.stringify(pack.tier_chains, null, 2),
    allowedProviders: pack.allowed_providers.join(", "),
    capabilities: JSON.stringify(pack.capability_requirements, null, 2),
    judgeModel: pack.judge_model ?? "",
  };
}

function parseObjectOfStringArrays(
  value: string,
  label: string,
): Record<string, string[]> {
  const parsed: unknown = JSON.parse(value);
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error(`${label} must be a JSON object.`);
  }
  for (const [key, item] of Object.entries(parsed)) {
    if (!Array.isArray(item) || item.some((entry) => typeof entry !== "string")) {
      throw new Error(`${label}.${key} must be an array of model IDs.`);
    }
  }
  return parsed as Record<string, string[]>;
}

function downloadJson(filename: string, value: unknown): void {
  const blob = new Blob([JSON.stringify(value, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export default function ModelPacksPanel() {
  const queryClient = useQueryClient();
  const importRef = useRef<HTMLInputElement | null>(null);
  const [selectedKey, setSelectedKey] = useState("");
  const [editor, setEditor] = useState<EditorState>(EMPTY_EDITOR);
  const [createOpen, setCreateOpen] = useState(false);
  const [createDraft, setCreateDraft] = useState({
    id: "",
    name: "",
    description: "",
    source: "effective" as ModelPackCreateRequest["source"],
  });
  const [workflow, setWorkflow] = useState("");
  const [validation, setValidation] =
    useState<ModelPackValidationResponse | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [archiveConfirm, setArchiveConfirm] = useState(false);

  const packsQuery = useQuery({
    queryKey: ["model-packs"],
    queryFn: listModelPacks,
  });
  const packs = packsQuery.data?.packs ?? [];
  const selected = useMemo(
    () => packs.find((pack) => refKey(pack) === selectedKey) ?? null,
    [packs, selectedKey],
  );

  useEffect(() => {
    if (packs.length === 0) return;
    const currentStillExists = packs.some((pack) => refKey(pack) === selectedKey);
    if (!currentStillExists) {
      const active = packsQuery.data?.active;
      const next =
        (active && packs.find((pack) => refKey(pack) === refKey(active))) ??
        packs[0];
      if (next) {
        setSelectedKey(refKey(next));
        setEditor(editorFor(next));
      }
    }
  }, [packs, packsQuery.data?.active, selectedKey]);

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["model-packs"] });
  };

  const createMutation = useMutation({
    mutationFn: createModelPack,
    onSuccess: async (pack) => {
      toast.success(`Created ${pack.name} v${pack.version}`);
      setCreateOpen(false);
      setCreateDraft({ id: "", name: "", description: "", source: "effective" });
      await refresh();
      setSelectedKey(refKey(pack));
      setEditor(editorFor(pack));
    },
  });

  const versionMutation = useMutation({
    mutationFn: ({
      packId,
      update,
    }: {
      packId: string;
      update: ModelPackUpdateRequest;
    }) => versionModelPack(packId, update),
    onSuccess: async (pack) => {
      toast.success(`Saved immutable version ${pack.version}`);
      await refresh();
      setSelectedKey(refKey(pack));
      setEditor(editorFor(pack));
    },
    onError: (error) => setFormError(error.message),
  });

  const saveNewVersion = () => {
    if (!selected) return;
    try {
      const update: ModelPackUpdateRequest = {
        name: editor.name.trim(),
        description: editor.description.trim(),
        tier_chains: parseObjectOfStringArrays(editor.tierChains, "tier_chains"),
        allowed_providers: editor.allowedProviders
          .split(",")
          .map((value) => value.trim())
          .filter(Boolean),
        capability_requirements: parseObjectOfStringArrays(
          editor.capabilities,
          "capability_requirements",
        ),
        judge_model: editor.judgeModel.trim() || null,
      };
      setFormError(null);
      versionMutation.mutate({ packId: selected.id, update });
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "Invalid model pack");
    }
  };

  const actionMutation = useMutation({
    mutationFn: async (action: "validate" | "activate" | "archive" | "export") => {
      if (!selected) throw new Error("Select a model pack.");
      const ref = { id: selected.id, version: selected.version };
      if (action === "validate") return validateModelPack(ref);
      if (action === "activate") return activateModelPack(ref);
      if (action === "export") return exportModelPack(ref);
      const dependencies = await getModelPackDependencies(ref);
      if (dependencies.globally_active || dependencies.workflows.length > 0) {
        throw new Error(
          `Pack is still used by ${dependencies.globally_active ? "the global default" : dependencies.workflows.join(", ")}.`,
        );
      }
      return archiveModelPack(ref);
    },
    onSuccess: async (result, action) => {
      if (action === "validate" && "valid" in result) {
        setValidation(result);
        toast[result.valid ? "success" : "error"](
          result.valid ? "Pack validation passed" : "Pack validation failed",
        );
      } else if (action === "export" && "schema_version" in result) {
        downloadJson(
          `${result.pack.id}-v${result.pack.version}.model-pack.json`,
          result,
        );
      } else {
        toast.success(action === "activate" ? "Global pack activated" : "Pack archived");
        setArchiveConfirm(false);
        await refresh();
      }
    },
    onError: (error) => toast.error(error.message),
  });

  const bindMutation = useMutation({
    mutationFn: async () => {
      if (!selected || !workflow.trim()) throw new Error("Enter a workflow name.");
      return bindModelPack(
        { id: selected.id, version: selected.version },
        workflow.trim(),
      );
    },
    onSuccess: async () => {
      toast.success(`Bound pack to ${workflow.trim()}`);
      setWorkflow("");
      await refresh();
    },
    onError: (error) => toast.error(error.message),
  });

  const clearBindingMutation = useMutation({
    mutationFn: clearModelPackBinding,
    onSuccess: async (_result, workflowName) => {
      toast.success(`Removed ${workflowName} binding`);
      await refresh();
    },
    onError: (error) => toast.error(error.message),
  });

  const duplicateMutation = useMutation({
    mutationFn: async () => {
      if (!selected) throw new Error("Select a model pack.");
      const id = globalThis.prompt("New pack ID", `${selected.id}-copy`)?.trim();
      if (!id) throw new Error("Duplicate cancelled.");
      return duplicateModelPack(
        { id: selected.id, version: selected.version },
        { new_id: id, name: `${selected.name} copy` },
      );
    },
    onSuccess: async (pack) => {
      toast.success(`Duplicated as ${pack.id}`);
      await refresh();
      setSelectedKey(refKey(pack));
      setEditor(editorFor(pack));
    },
    onError: (error) => {
      if (error.message !== "Duplicate cancelled.") toast.error(error.message);
    },
  });

  const handleImport = async (file: File | undefined) => {
    if (!file) return;
    try {
      const document = JSON.parse(await file.text()) as {
        schema_version: 1;
        pack: ModelPackCreateRequest;
      };
      const pack = await importModelPack(document);
      toast.success(`Imported ${pack.name}`);
      await refresh();
      setSelectedKey(refKey(pack));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Import failed");
    } finally {
      if (importRef.current) importRef.current.value = "";
    }
  };

  return (
    <div className="mx-auto w-full max-w-7xl space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="max-w-3xl">
          <div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-el-accent-strong">
            Versioned routing policy
          </div>
          <h1 className="font-display text-[36px] font-medium leading-tight text-el-ink">
            Model packs
          </h1>
          <p className="mt-3 text-[14px] leading-6 text-el-muted">
            Build immutable, instance-scoped routing policies. Validate them,
            activate a global default, bind an exact version to a workflow,
            and retain the selected snapshot with every run.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <input
            ref={importRef}
            type="file"
            accept="application/json,.json"
            className="sr-only"
            aria-label="Import model pack"
            onChange={(event) => void handleImport(event.target.files?.[0])}
          />
          <Button variant="outline" onClick={() => importRef.current?.click()}>
            <Upload aria-hidden="true" /> Import
          </Button>
          <Button onClick={() => setCreateOpen((open) => !open)}>
            <Plus aria-hidden="true" /> New pack
          </Button>
        </div>
      </div>

      {createOpen && (
        <form
          className="grid gap-4 border-y border-el-divider py-6 md:grid-cols-4"
          onSubmit={(event) => {
            event.preventDefault();
            createMutation.mutate({
              id: createDraft.id.trim(),
              name: createDraft.name.trim(),
              description: createDraft.description.trim(),
              source: createDraft.source,
            });
          }}
        >
          <label className="space-y-2 text-[12px] font-semibold text-el-secondary">
            Stable ID
            <Input
              value={createDraft.id}
              pattern="[a-z0-9][a-z0-9_-]*"
              required
              onChange={(event) =>
                setCreateDraft((draft) => ({ ...draft, id: event.target.value }))
              }
            />
          </label>
          <label className="space-y-2 text-[12px] font-semibold text-el-secondary">
            Name
            <Input
              value={createDraft.name}
              required
              onChange={(event) =>
                setCreateDraft((draft) => ({ ...draft, name: event.target.value }))
              }
            />
          </label>
          <label className="space-y-2 text-[12px] font-semibold text-el-secondary">
            Seed from
            <select
              className="h-10 w-full border border-el-divider bg-el-raised px-3 text-[13px]"
              value={createDraft.source}
              onChange={(event) =>
                setCreateDraft((draft) => ({
                  ...draft,
                  source: event.target.value as ModelPackCreateRequest["source"],
                }))
              }
            >
              <option value="effective">Effective routing</option>
              <option value="defaults">Built-in defaults</option>
              <option value="explicit">Empty explicit pack</option>
            </select>
          </label>
          <div className="flex items-end gap-2">
            <Button type="submit" disabled={createMutation.isPending}>
              Create version 1
            </Button>
            <Button type="button" variant="ghost" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
          </div>
        </form>
      )}

      {packsQuery.isError && (
        <div role="alert" className="border border-el-danger bg-el-surface p-4 text-el-danger">
          Could not load model packs: {packsQuery.error.message}
        </div>
      )}

      <div className="grid min-h-[520px] gap-8 lg:grid-cols-[300px_minmax(0,1fr)]">
        <aside className="border-r-0 border-el-divider lg:border-r lg:pr-6" aria-label="Model pack versions">
          <div className="mb-3 flex items-center justify-between text-[11px] font-semibold uppercase tracking-[0.12em] text-el-muted">
            <span>Pack versions</span>
            <span>{packs.length}</span>
          </div>
          <div className="space-y-1">
            {packsQuery.isLoading && <p className="py-8 text-sm text-el-muted">Loading packs…</p>}
            {!packsQuery.isLoading && packs.length === 0 && (
              <div className="border border-dashed border-el-divider p-5 text-[13px] leading-5 text-el-muted">
                No model packs yet. Create one from the effective route, built-in defaults, or an explicit policy.
              </div>
            )}
            {packs.map((pack) => {
              const active =
                packsQuery.data?.active && refKey(packsQuery.data.active) === refKey(pack);
              return (
                <button
                  key={refKey(pack)}
                  type="button"
                  onClick={() => {
                    setSelectedKey(refKey(pack));
                    setEditor(editorFor(pack));
                    setValidation(null);
                    setFormError(null);
                    setArchiveConfirm(false);
                  }}
                  className={`w-full border-l-2 px-3 py-3 text-left transition-colors ${
                    refKey(pack) === selectedKey
                      ? "border-el-accent bg-el-subtle"
                      : "border-transparent hover:bg-el-surface"
                  }`}
                >
                  <span className="flex items-center gap-2 text-[13px] font-semibold text-el-ink">
                    {pack.name}
                    {active && <CheckCircle2 className="h-4 w-4 text-el-success" aria-label="Active" />}
                  </span>
                  <span className="mt-1 block font-mono text-[10px] text-el-muted">
                    {pack.id}@{pack.version} · {pack.source}
                    {pack.archived ? " · archived" : ""}
                  </span>
                </button>
              );
            })}
          </div>
        </aside>

        <section aria-label="Selected model pack">
          {!selected ? (
            <div className="grid h-full place-items-center border border-dashed border-el-divider text-sm text-el-muted">
              Select or create a model pack.
            </div>
          ) : (
            <div className="space-y-7">
              <div className="flex flex-wrap items-start justify-between gap-4 border-b border-el-divider pb-5">
                <div>
                  <div className="font-mono text-[11px] text-el-muted">
                    {selected.id}@{selected.version}
                  </div>
                  <h2 className="mt-1 text-[22px] font-semibold text-el-ink">{selected.name}</h2>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button type="button" data-testid="validate-pack" variant="outline" size="sm" onClick={() => actionMutation.mutate("validate")}>
                    <ShieldCheck aria-hidden="true" /> Validate
                  </Button>
                  <Button type="button" variant="outline" size="sm" onClick={() => actionMutation.mutate("activate")} disabled={selected.archived}>
                    <CheckCircle2 aria-hidden="true" /> Activate
                  </Button>
                  <Button type="button" variant="outline" size="sm" onClick={() => duplicateMutation.mutate()}>
                    <Copy aria-hidden="true" /> Duplicate
                  </Button>
                  <Button type="button" variant="outline" size="sm" onClick={() => actionMutation.mutate("export")}>
                    <Download aria-hidden="true" /> Export
                  </Button>
                  <Button type="button" variant="ghost" size="sm" onClick={() => setArchiveConfirm(true)} disabled={selected.archived}>
                    <Archive aria-hidden="true" /> Archive
                  </Button>
                </div>
              </div>

              {archiveConfirm && !selected.archived && (
                <div className="flex flex-wrap items-center justify-between gap-3 border-l-2 border-el-danger bg-el-surface px-4 py-3" role="alert">
                  <p className="text-[13px] text-el-secondary">
                    Archive <strong className="text-el-ink">{selected.name} v{selected.version}</strong>? Existing run provenance remains available, but this version can no longer be selected.
                  </p>
                  <div className="flex gap-2">
                    <Button variant="ghost" size="sm" onClick={() => setArchiveConfirm(false)}>Cancel</Button>
                    <Button variant="destructive" size="sm" onClick={() => actionMutation.mutate("archive")} disabled={actionMutation.isPending}>Confirm archive</Button>
                  </div>
                </div>
              )}

              {validation && (
                <div
                  className={`border-l-2 px-4 py-3 text-[13px] ${
                    validation.valid
                      ? "border-el-success bg-el-surface text-el-success"
                      : "border-el-danger bg-el-surface text-el-danger"
                  }`}
                  role="status"
                >
                  <strong>{validation.valid ? "Validation passed" : "Validation failed"}</strong>
                  {validation.issues.map((issue) => (
                    <div key={`${issue.code}-${issue.model ?? ""}`} className="mt-1 text-el-secondary">
                      {issue.severity}: {issue.message}
                    </div>
                  ))}
                </div>
              )}

              <div className="grid gap-5 md:grid-cols-2">
                <label className="space-y-2 text-[12px] font-semibold text-el-secondary">
                  Name
                  <Input aria-label="Pack name" value={editor.name} onChange={(event) => setEditor((value) => ({ ...value, name: event.target.value }))} />
                </label>
                <label className="space-y-2 text-[12px] font-semibold text-el-secondary">
                  Allowed providers
                  <Input placeholder="openai, anthropic, ollama" value={editor.allowedProviders} onChange={(event) => setEditor((value) => ({ ...value, allowedProviders: event.target.value }))} />
                </label>
                <label className="space-y-2 text-[12px] font-semibold text-el-secondary md:col-span-2">
                  Description
                  <Input aria-label="Pack description" value={editor.description} onChange={(event) => setEditor((value) => ({ ...value, description: event.target.value }))} />
                </label>
                <label className="space-y-2 text-[12px] font-semibold text-el-secondary">
                  Tier chains (JSON)
                  <Textarea className="min-h-56 font-mono text-[12px]" value={editor.tierChains} onChange={(event) => setEditor((value) => ({ ...value, tierChains: event.target.value }))} />
                </label>
                <label className="space-y-2 text-[12px] font-semibold text-el-secondary">
                  Capability requirements (JSON)
                  <Textarea className="min-h-56 font-mono text-[12px]" value={editor.capabilities} onChange={(event) => setEditor((value) => ({ ...value, capabilities: event.target.value }))} />
                </label>
                <label className="space-y-2 text-[12px] font-semibold text-el-secondary md:col-span-2">
                  Judge model
                  <Input placeholder="provider:model" value={editor.judgeModel} onChange={(event) => setEditor((value) => ({ ...value, judgeModel: event.target.value }))} />
                </label>
              </div>

              {formError && <p role="alert" className="text-[13px] text-el-danger">{formError}</p>}

              <div className="flex flex-wrap items-center gap-3 border-y border-el-divider py-4">
                <Button onClick={saveNewVersion} disabled={versionMutation.isPending || selected.archived}>
                  Save as version {selected.version + 1}
                </Button>
                <span className="text-[12px] text-el-muted">Existing versions remain immutable.</span>
              </div>

              <section aria-labelledby="binding-title">
                <div className="flex items-center gap-2">
                  <GitBranch className="h-4 w-4 text-el-accent-strong" aria-hidden="true" />
                  <h3 id="binding-title" className="text-[15px] font-semibold text-el-ink">Workflow binding</h3>
                </div>
                <p className="mt-2 text-[12px] leading-5 text-el-muted">
                  Bind this exact version to a workflow. A run-level selection can still override it.
                </p>
                <div className="mt-3 flex max-w-xl gap-2">
                  <Input aria-label="Workflow name" placeholder="code-review" value={workflow} onChange={(event) => setWorkflow(event.target.value)} />
                  <Button variant="outline" onClick={() => bindMutation.mutate()} disabled={!workflow.trim() || selected.archived}>
                    Bind
                  </Button>
                </div>
                {packsQuery.data && Object.keys(packsQuery.data.workflow_bindings).length > 0 && (
                  <dl className="mt-4 grid gap-2 text-[12px] sm:grid-cols-2">
                    {Object.entries(packsQuery.data.workflow_bindings).map(([name, ref]) => (
                      <div key={name} className="flex items-center justify-between gap-3 border-b border-el-divider-soft py-2">
                        <dt className="text-el-secondary">{name}</dt>
                        <dd className="flex items-center gap-2">
                          <span className="font-mono text-el-muted">{ref.id}@{ref.version}</span>
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            aria-label={`Remove ${name} binding`}
                            onClick={() => clearBindingMutation.mutate(name)}
                            disabled={clearBindingMutation.isPending}
                          >
                            Remove
                          </Button>
                        </dd>
                      </div>
                    ))}
                  </dl>
                )}
              </section>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
