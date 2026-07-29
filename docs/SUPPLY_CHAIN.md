# Local model integrity

The repository includes a SHA-256 verifier for local model files and
directories. It compares a model path with a reviewed trust file.

This is an integrity check, not signed provenance. It proves only that the
local bytes match the configured digest.

## Current enforcement boundary

`agentic_v2.models.weight_integrity.verify_model_weights()` implements the
check. `tools/llm/provider_adapters.py` calls it before its local-model load
path.

The native `OnnxBackend` and the LangChain local ONNX builder do not currently
call the verifier. Setting strict mode therefore does not make every runtime
model-loading path fail closed. See
[known limitations](KNOWN_LIMITATIONS.md) before relying on this control.

## Trust file

The default file is:

```text
agentic-workflows-v2/agentic_v2/config/defaults/trusted_model_hashes.yaml
```

Its JSON Schema is:

```text
agentic-workflows-v2/schemas/trusted_model_hashes.schema.json
```

Entry shape:

```yaml
schema_version: trusted-model-hashes.v1
models:
  - id: reviewed-model
    path: C:\models\reviewed-model
    sha256: 64-character-lowercase-sha256
    algorithm: sha256
    source: internal-model-release
    notes: Optional review context
```

Paths may contain `~` or environment variables. Matching uses resolved paths.
IDs must be unique and unknown entry fields are rejected.

For a directory, the digest is deterministic: each file's relative path and
SHA-256 digest are added in sorted order. Adding, removing, renaming, or
changing a file changes the directory digest.

## Compute a digest

From the repository root:

```powershell
python -c "from pathlib import Path; from agentic_v2.models.weight_integrity import compute_model_sha256; print(compute_model_sha256(Path(r'C:\models\reviewed-model')))"
```

Review where the model came from before adding its digest. Computing a hash
from an untrusted download and immediately trusting that same hash does not
establish a trustworthy source.

## Verify explicitly

```powershell
python -c "from pathlib import Path; from agentic_v2.models.weight_integrity import verify_model_weights; print(verify_model_weights(Path(r'C:\models\reviewed-model')))"
```

Without strict mode:

- a match returns `verified`;
- an unknown path returns `unknown` and logs a warning;
- a mismatch returns `mismatch` and logs a warning.

Enable strict behavior inside code paths that call the verifier:

```powershell
$env:AGENTIC_STRICT_MODEL_VERIFY = "1"
```

In strict mode, an unknown hash, mismatch, or malformed trust file raises
`ModelWeightVerificationError`.

Select another trust file with:

```powershell
$env:AGENTIC_TRUSTED_MODEL_HASHES = "C:\secure-config\model-hashes.yaml"
```

Protect that file separately from the model artifacts. If an attacker can
change both the model and its expected digest, the check has no value.

## Test

```powershell
python -m pytest agentic-workflows-v2\tests\test_weight_integrity.py -q
```

## What this does not provide

The current control does not provide:

- a publisher identity;
- a signed attestation;
- a transparency-log record;
- build inputs or build instructions;
- proof that the model is safe or suitable;
- complete enforcement across all model loaders.

Signed SLSA or in-toto provenance could add producer and build identity in a
future design. Sigstore could verify signatures and transparency-log inclusion.
Those mechanisms are not implemented here and should not be claimed as current
protection.
