// =============================================================================
// ARP — reference IaC (NOT DEPLOYED, $0)
// =============================================================================
// This Bicep is prod-readiness EVIDENCE only. The live proof of the Redis-CAS +
// horizontal-scale story is the local k6 run + the GitHub Pages report. This
// template is authored, `az bicep build`/`lint`-clean, and secret-free, but is
// never deployed (no `az login`, no `az deployment`). The companion deploy
// workflow (.github/workflows/infra-deploy.yml) is workflow_dispatch-only and
// OIDC-based, and is intentionally never run.
//
// It maps the local load topology to the equivalent managed Azure services:
//   nginx round-robin + N replicas  ->  Container Apps (HTTP scale rules, N..M replicas)
//   local Redis (shared CAS store)   ->  Azure Cache for Redis
//   OTel collector + Jaeger          ->  Log Analytics + Application Insights
//   local image build                ->  Azure Container Registry
//   (no static keys)                 ->  user-assigned managed identity + AcrPull
// -----------------------------------------------------------------------------

targetScope = 'resourceGroup'

@description('Deployment environment short name (e.g. dev, stage, prod).')
@allowed([
  'dev'
  'stage'
  'prod'
])
param environmentName string = 'dev'

@description('Azure region for all resources. Defaults to the resource group location.')
param location string = resourceGroup().location

@description('Base name used to derive resource names. 3-12 lowercase alphanumerics.')
@minLength(3)
@maxLength(12)
param baseName string = 'arp'

@description('Container image reference for the ARP backend (e.g. <acr>.azurecr.io/arp:tag). The ACR built below is the intended source.')
param containerImage string = 'mcr.microsoft.com/k8se/quickstart:latest'

@description('Minimum replica count (horizontal-scale floor). >=2 mirrors the multi-replica CAS proof.')
@minValue(1)
@maxValue(25)
param minReplicas int = 2

@description('Maximum replica count (horizontal-scale ceiling).')
@minValue(1)
@maxValue(30)
param maxReplicas int = 10

@description('Concurrent-requests-per-replica target that drives HTTP autoscale.')
@minValue(1)
param concurrentRequestsPerReplica int = 50

@description('Container CPU cores per replica.')
param cpuCores string = '0.5'

@description('Container memory per replica.')
param memorySize string = '1.0Gi'

// Deterministic, collision-resistant suffix derived from the RG id.
var suffix = uniqueString(resourceGroup().id)
var names = {
  acr: toLower('${baseName}acr${suffix}')
  logAnalytics: '${baseName}-law-${environmentName}'
  appInsights: '${baseName}-ai-${environmentName}'
  redis: '${baseName}-redis-${environmentName}-${suffix}'
  identity: '${baseName}-id-${environmentName}'
  caenv: '${baseName}-cae-${environmentName}'
  app: '${baseName}-app-${environmentName}'
}

var tags = {
  workload: 'agentic-runtime-platform'
  purpose: 'reference-iac-not-deployed'
  costCenter: 'zero-dollar-proof'
  environment: environmentName
}

// -----------------------------------------------------------------------------
// Observability: Log Analytics + Application Insights (the OTel target)
// -----------------------------------------------------------------------------
resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: names.logAnalytics
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
    features: {
      enableLogAccessUsingOnlyResourcePermissions: true
    }
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: names.appInsights
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
    IngestionMode: 'LogAnalytics'
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

// -----------------------------------------------------------------------------
// Identity: user-assigned managed identity (no static credentials anywhere)
// -----------------------------------------------------------------------------
resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: names.identity
  location: location
  tags: tags
}

// -----------------------------------------------------------------------------
// Registry: ACR (image source; pulled via managed identity, admin user OFF)
// -----------------------------------------------------------------------------
resource acr 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = {
  name: names.acr
  location: location
  tags: tags
  sku: {
    name: 'Standard'
  }
  properties: {
    adminUserEnabled: false // no static registry creds — identity + AcrPull only
    publicNetworkAccess: 'Enabled'
  }
}

// AcrPull for the user-assigned identity, scoped to this registry.
var acrPullRoleId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '7f951dda-4ed3-4680-a7ca-43fe172d538d'
)

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, identity.id, acrPullRoleId)
  scope: acr
  properties: {
    principalId: identity.properties.principalId
    roleDefinitionId: acrPullRoleId
    principalType: 'ServicePrincipal'
  }
}

// -----------------------------------------------------------------------------
// Shared CAS store: Azure Cache for Redis (the cross-replica circuit-breaker
// state store — the managed equivalent of the local Redis in the load proof)
// -----------------------------------------------------------------------------
resource redis 'Microsoft.Cache/redis@2024-03-01' = {
  name: names.redis
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'Standard'
      family: 'C'
      capacity: 1
    }
    enableNonSslPort: false
    minimumTlsVersion: '1.2'
    redisConfiguration: {
      'maxmemory-policy': 'volatile-lru'
    }
  }
}

// -----------------------------------------------------------------------------
// Container Apps Environment (wired to Log Analytics for OTel/log ingestion)
// -----------------------------------------------------------------------------
resource caEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: names.caenv
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        // Key is read at deploy time from the LA workspace; never hardcoded.
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

// -----------------------------------------------------------------------------
// The ARP backend app: multi-replica with HTTP-concurrency autoscale.
// Redis connection + App Insights connection string flow in via secrets sourced
// from the resources above (listKeys), never from literals in this template.
// -----------------------------------------------------------------------------
resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: names.app
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: caEnv.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8010
        transport: 'auto'
        // Platform-managed ingress already load-balances across replicas — this
        // is the managed equivalent of the nginx round-robin in the load proof.
        allowInsecure: false
      }
      registries: [
        {
          server: '${names.acr}.azurecr.io'
          identity: identity.id
        }
      ]
      secrets: [
        {
          // redis://:<key>@host:6380 over TLS. Built from listKeys at deploy
          // time — no secret material is committed to this template.
          name: 'redis-url'
          value: 'rediss://:${redis.listKeys().primaryKey}@${redis.properties.hostName}:6380/0'
        }
        {
          name: 'appinsights-connection-string'
          value: appInsights.properties.ConnectionString
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'arp-backend'
          image: containerImage
          resources: {
            cpu: json(cpuCores)
            memory: memorySize
          }
          env: [
            {
              name: 'REDIS_URL'
              secretRef: 'redis-url'
            }
            {
              name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
              secretRef: 'appinsights-connection-string'
            }
            {
              name: 'AGENTIC_DEFAULT_ADAPTER'
              value: 'native'
            }
            {
              name: 'AGENTIC_TRACING'
              value: '1'
            }
            {
              name: 'OTEL_SERVICE_NAME'
              value: 'agentic-runtime-platform'
            }
          ]
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
        rules: [
          {
            name: 'http-concurrency'
            http: {
              metadata: {
                concurrentRequests: string(concurrentRequestsPerReplica)
              }
            }
          }
        ]
      }
    }
  }
}

// -----------------------------------------------------------------------------
// Outputs (non-secret). Endpoints + ids for downstream wiring / verification.
// -----------------------------------------------------------------------------
output appFqdn string = app.properties.configuration.ingress.fqdn
output acrLoginServer string = acr.properties.loginServer
output redisHostName string = redis.properties.hostName
output managedIdentityClientId string = identity.properties.clientId
output appInsightsName string = appInsights.name
output minReplicasConfigured int = minReplicas
output maxReplicasConfigured int = maxReplicas
