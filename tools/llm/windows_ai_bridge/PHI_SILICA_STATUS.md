# Phi Silica bridge status

This directory contains a .NET command-line bridge between the Python model
client and the Windows AI Phi Silica API. Availability depends on the current
machine, Windows build, Windows App SDK, hardware, model installation, package
identity, and Limited Access Feature (LAF) authorization.

Do not treat this file as proof that Phi Silica works on a specific machine.
Run the checks below on that machine.

> **Credential notice:** Never commit a LAF token or attestation. A token was
> previously present in this file. Treat that value as exposed and rotate or
> revoke it with the issuer.

## What is implemented

`Program.cs` supports:

| Command | Result |
| --- | --- |
| `--check` | Prints `AVAILABLE` when `LanguageModel.GetReadyState()` is ready. |
| `--info` | Prints model, readiness, LAF, platform, and runtime information as JSON. |
| `--unlock` | Attempts a LAF unlock and prints a JSON report. |
| `<prompt>` | Creates the system language model and prints generated text. |

The Python entry point is `tools.llm.windows_ai.WindowsAIClient`. Model IDs use
the `windows-ai:` prefix, normally `windows-ai:phi-silica`.

## Prerequisites

- a Windows device supported by the current Phi Silica release;
- a compatible Windows build and Windows App SDK;
- the .NET 8 SDK;
- the required system model installed and ready; and
- LAF authorization when required by the selected release channel.

Microsoft has announced that Aion Instruct will replace Phi Silica. Check the
current [Phi Silica documentation](https://learn.microsoft.com/windows/ai/apis/phi-silica)
before investing in new integration work.

## Build and check

From this directory:

```powershell
dotnet build .\PhiSilicaBridge.csproj -c Release
dotnet run --project .\PhiSilicaBridge.csproj -c Release -- --check
dotnet run --project .\PhiSilicaBridge.csproj -c Release -- --info
```

Exit code `0` from `--check` means the model reported ready at that time. A
successful build alone does not prove that the model, hardware, or access
requirements are satisfied.

To test generation:

```powershell
dotnet run --project .\PhiSilicaBridge.csproj -c Release -- `
  "Explain the difference between a process and a thread."
```

## LAF configuration

When a LAF token is required, provide all three values through the environment:

```powershell
$env:PHI_SILICA_LAF_FEATURE_ID = "<feature-id>"
$env:PHI_SILICA_LAF_TOKEN = "<token>"
$env:PHI_SILICA_LAF_ATTESTATION = "<attestation>"

dotnet run --project .\PhiSilicaBridge.csproj -c Release -- --unlock
```

Use a secret manager or a temporary process environment. Do not put these
values in tracked files, command history, screenshots, or issue reports.

The bridge reports whether each value is present but does not print the token
or attestation.

## Packaged identity build

`build-with-laf.ps1` builds the executable, compiles `laf_identity.rc`, and
injects that resource into the executable. It also downloads and runs Resource
Hacker when that tool is not already present.

Review the script, download source, checksum, license, and hard-coded identity
before running it. In controlled build environments, provide a reviewed copy
of the resource tool instead of downloading executable code during the build.

The resource identity in this repository is project-specific. Replace it with
the identity registered for the application being deployed.

## Interpreting failures

| Result | What to check |
| --- | --- |
| `NOT_AVAILABLE` | Supported hardware, Windows build, model installation, driver, and rollout state. |
| `UnauthorizedAccessException` | LAF authorization, package identity, and the `systemAIModels` capability. |
| Incomplete LAF configuration | Set feature ID, token, and attestation together. |
| `EnsureReadyAsync` fails | Windows Update or model download state, network access, disk space, and the current Microsoft requirements. |
| Python reports that the project is missing | Run from this checkout and confirm `tools/llm/windows_ai_bridge/PhiSilicaBridge.csproj` exists. |

Use `diagnose-npu.ps1` for local hardware diagnostics. Its output describes the
current machine only and should not be committed if it contains device or user
details.

## Security and support boundary

- Phi Silica input and output remain local to the Windows API, but the
  surrounding process can still log, persist, or forward them.
- The bridge sends prompts as command-line arguments. Other processes with
  sufficient access may be able to inspect command lines. Do not use this
  bridge for sensitive prompts without addressing that exposure.
- The bridge is an optional tools-layer integration. It does not prove that
  the workflow runtime's native or LangChain adapters support every
  `windows-ai:` model path.
- Hardware and platform support change independently of this repository.

See the official
[Phi Silica guide](https://learn.microsoft.com/windows/ai/apis/phi-silica) and
[Windows AI troubleshooting guide](https://learn.microsoft.com/windows/ai/apis/troubleshooting)
for current platform requirements.
