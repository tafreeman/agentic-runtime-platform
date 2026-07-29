# Azure reference template

The Bicep files in this directory describe a possible managed deployment. They
are not deployed by the repository's normal CI and do not prove that a live
Azure environment exists.

## Service mapping

| Local component | Azure resource |
| --- | --- |
| FastAPI replicas and nginx entry point | Azure Container Apps |
| Shared Redis circuit-breaker state | Azure Cache for Redis |
| Container image | Azure Container Registry |
| Logs and traces | Log Analytics and Application Insights |
| Registry access | User-assigned managed identity with `AcrPull` |

The template's minimum replica count defaults to two.

## Parameters and secrets

`main.bicepparam.example` is a placeholder file. Copy it to the ignored
`main.bicepparam` before an authorized deployment.

The template resolves service-generated values at deployment time and uses a
managed identity for registry pulls. Do not add Redis keys, connection strings,
provider tokens, or service-principal secrets to committed parameter files.

## Validate without deploying

From the repository root:

```powershell
az bicep install
az bicep build --file infra\azure\main.bicep
az bicep lint --file infra\azure\main.bicep
```

`build` creates `main.json`; treat it as generated output unless a workflow
explicitly requires it.

## Deployment workflow

`.github/workflows/infra-deploy.yml` is manually triggered. It requires a
typed confirmation and runs an Azure `what-if` preview before deployment. Its
authentication design uses GitHub OIDC rather than a stored client secret.

A manual workflow is still a real, billable infrastructure action. Review the
subscription, region, resource names, SKU costs, identity permissions, and
`what-if` output before authorizing it.

The current local load evidence is documented separately in
[the load harness](../../load/README.md).
