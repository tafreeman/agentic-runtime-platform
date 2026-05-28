# Supply Chain Integrity

This project verifies local ONNX model weights with SHA-256 before loading
them through the `local:*` provider path. The current control is hash-based
integrity, not signed provenance.

## Trusted Model Hashes

Trusted local model hashes live in
`agentic-workflows-v2/agentic_v2/config/defaults/trusted_model_hashes.yaml`.
The machine-readable schema lives at
`agentic-workflows-v2/schemas/trusted_model_hashes.schema.json`. The YAML shape
is:

```yaml
schema_version: trusted-model-hashes.v1
models:
  - id: stable-human-readable-id
    path: ~/.cache/aigallery/vendor--model/path/to/onnx-folder
    sha256: 64-character-lowercase-sha256
    algorithm: sha256
    source: local-aigallery-discovery
    notes: Optional context for maintainers
```

Paths may use `~` or environment variables. Directory hashes are computed
deterministically from every file below the directory, using each relative file
path plus its SHA-256 digest.

To add a trusted hash:

1. Install or place the model in its final local path.
2. Compute the digest with the same runtime function:

```powershell
uv run --package agentic-workflows-v2 python -c "from pathlib import Path; from agentic_v2.models.weight_integrity import compute_model_sha256; print(compute_model_sha256(Path(r'C:\path\to\model-or-folder')))"
```

3. Add one YAML entry with that exact path and digest.
4. Run:

```powershell
uv run --package agentic-workflows-v2 pytest agentic-workflows-v2/tests/test_weight_integrity.py -q
uv run --package agentic-workflows-v2 ruff check agentic-workflows-v2/agentic_v2/models/weight_integrity.py tools/llm/provider_adapters.py agentic-workflows-v2/tests/test_weight_integrity.py
```

## Strict Mode

By default, unknown or mismatched model hashes are logged as warnings and local
loading continues. This keeps developer machines usable while surfacing drift.

Set strict mode to block untrusted or tampered weights:

```powershell
$env:AGENTIC_STRICT_MODEL_VERIFY = "1"
```

In strict mode:

- a configured hash mismatch raises `ModelWeightVerificationError`;
- a missing trusted hash raises `ModelWeightVerificationError`;
- malformed trusted-hash YAML raises `ModelWeightVerificationError`.

Use `AGENTIC_TRUSTED_MODEL_HASHES` to point at an alternate trust file for a
deployment or test fixture.

## SLSA Level 1 Fit

SLSA Build Level 1 is the "provenance exists" level: it asks producers to use a
consistent build process, run on a Build L1 platform, and distribute provenance
that describes how an artifact was built. SLSA notes that L1 provenance may be
incomplete or unsigned, so it helps with mistakes and inventory but is not a
strong tamper-resistance boundary.

This repository's model hash control is a consumer-side expectation check. It
supports SLSA-style verification by comparing the local artifact digest against
a preconfigured trust map, but it does not by itself produce SLSA provenance.
For model weights, a future producer-side process should publish SLSA Build
Provenance or equivalent in-toto attestations alongside each model artifact.

## Sigstore Future Path

Sigstore is the natural next step once model artifacts have signed
attestations. A future implementation should:

- sign model artifacts or provenance with Sigstore keyless signing;
- verify the Fulcio identity certificate against an expected publisher or CI
  identity;
- verify Rekor transparency-log inclusion;
- compare the attestation subject digest to the local model digest;
- enforce expected builder identity, source repository, build type, and build
  parameters before loading weights.

Until that exists, SHA-256 trust entries remain the enforcement mechanism.

## References

- SLSA Build Track Basics, Version 1.2:
  https://slsa.dev/spec/v1.2/build-track-basics
- SLSA Verifying Artifacts, Version 1.2:
  https://slsa.dev/spec/v1.2/verifying-artifacts
- SLSA Distributing Provenance, Version 1.2:
  https://slsa.dev/spec/v1.2/distributing-provenance
- Sigstore overview:
  https://docs.sigstore.dev/
- Sigstore keyless signing overview:
  https://docs.sigstore.dev/cosign/signing/overview/
- Python `hashlib`:
  https://docs.python.org/3/library/hashlib.html
- PyYAML `safe_load`:
  https://pyyaml.org/wiki/PyYAMLDocumentation
