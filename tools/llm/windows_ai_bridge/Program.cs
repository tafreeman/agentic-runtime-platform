using Microsoft.Windows.AI;
using Microsoft.Windows.AI.Text;
using Windows.ApplicationModel;
using System.Text.Json;

namespace PhiSilicaBridge;

/// <summary>
/// Command-line bridge for Windows AI Phi Silica.
/// Called from Python via subprocess.
/// </summary>
class Program
{
    static async Task<int> Main(string[] args)
    {
        try
        {
            if (args.Length == 0 || args[0] == "--help" || args[0] == "-h")
            {
                PrintHelp();
                return args.Length == 0 ? 1 : 0;
            }

            if (args[0] == "--check")
            {
                var opts = ParseOptions(args.Skip(1).ToArray());
                return await CheckAvailability(opts);
            }

            if (args[0] == "--info")
            {
                var opts = ParseOptions(args.Skip(1).ToArray());
                return await GetModelInfo(opts);
            }

            if (args[0] == "--unlock")
            {
                var opts = ParseOptions(args.Skip(1).ToArray());
                return UnlockOnly(opts);
            }

            // Generate text from prompt
            var prompt = string.Join(" ", args);
            return await GenerateText(prompt);
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"FATAL ERROR: {ex.Message}");
            return 1;
        }

        static void PrintHelp()
        {
            Console.WriteLine(@"PhiSilicaBridge - Windows AI Phi Silica CLI

Usage:
  PhiSilicaBridge <prompt>       Generate text from prompt
  PhiSilicaBridge --check        Check if Phi Silica is available
  PhiSilicaBridge --info         Get model information as JSON
    PhiSilicaBridge --unlock       Attempt Limited Access Feature unlock (JSON)
  PhiSilicaBridge --help         Show this help

Limited Access Feature (LAF):
    Phi Silica APIs may require an unlock token depending on OS/App SDK channel.
    Configure these env vars (recommended) or pass CLI args:
        - PHI_SILICA_LAF_FEATURE_ID
        - PHI_SILICA_LAF_TOKEN
        - PHI_SILICA_LAF_ATTESTATION

    CLI options (for --info/--check/--unlock):
        --laf-feature-id <id>
        --laf-token <token>
        --laf-attestation <text>

Notes:
    - If you see UnauthorizedAccessException, you may need a packaged app with
        the systemAIModels capability, and/or a LAF token, depending on your setup.
    - Docs: https://learn.microsoft.com/windows/ai/apis/phi-silica

Requirements:
  - Windows 11 with NPU (Copilot+ PC)
  - Windows App SDK 1.8+

Example:
  PhiSilicaBridge ""Explain quantum computing in simple terms""
");
        }

        static Dictionary<string, string> ParseOptions(string[] args)
        {
            var opts = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            for (int i = 0; i < args.Length; i++)
            {
                var a = args[i];
                if (!a.StartsWith("--", StringComparison.Ordinal))
                {
                    continue;
                }

                var key = a;
                string value = "";
                if (i + 1 < args.Length && !args[i + 1].StartsWith("--", StringComparison.Ordinal))
                {
                    value = args[i + 1];
                    i++;
                }
                opts[key] = value;
            }
            return opts;
        }

        static (string? featureId, string? token, string? attestation, bool present) GetLafConfig(Dictionary<string, string> opts)
        {
            string? GetOpt(string name)
            {
                return opts.TryGetValue(name, out var v) && !string.IsNullOrWhiteSpace(v) ? v : null;
            }

            var featureId = GetOpt("--laf-feature-id") ?? Environment.GetEnvironmentVariable("PHI_SILICA_LAF_FEATURE_ID");
            var token = GetOpt("--laf-token") ?? Environment.GetEnvironmentVariable("PHI_SILICA_LAF_TOKEN");
            var attestation = GetOpt("--laf-attestation") ?? Environment.GetEnvironmentVariable("PHI_SILICA_LAF_ATTESTATION");

            var present = !string.IsNullOrWhiteSpace(featureId) || !string.IsNullOrWhiteSpace(token) || !string.IsNullOrWhiteSpace(attestation);
            return (featureId, token, attestation, present);
        }

        static object BuildLafReport(Dictionary<string, string> opts)
        {
            var (featureId, token, attestation, present) = GetLafConfig(opts);
            var report = new Dictionary<string, object?>
            {
                ["present"] = present,
                ["featureId_present"] = !string.IsNullOrWhiteSpace(featureId),
                ["token_present"] = !string.IsNullOrWhiteSpace(token),
                ["attestation_present"] = !string.IsNullOrWhiteSpace(attestation),
            };

            if (!present)
            {
                report["attempted"] = false;
                return report;
            }

            if (string.IsNullOrWhiteSpace(featureId) || string.IsNullOrWhiteSpace(token) || string.IsNullOrWhiteSpace(attestation))
            {
                report["attempted"] = false;
                report["error"] = "Incomplete LAF config. Need featureId + token + attestation.";
                return report;
            }

            try
            {
                var result = LimitedAccessFeatures.TryUnlockFeature(featureId, token, attestation);
                report["attempted"] = true;
                report["status"] = result.Status.ToString();
                report["featureId"] = result.FeatureId;
                report["estimatedRemovalDate"] = result.EstimatedRemovalDate.ToString();
                return report;
            }
            catch (Exception ex)
            {
                report["attempted"] = true;
                report["error"] = ex.Message;
                return report;
            }
        }

        static int UnlockOnly(Dictionary<string, string> opts)
        {
            var payload = new
            {
                model = "phi-silica",
                provider = "windows-ai",
                laf = BuildLafReport(opts),
                platform = Environment.OSVersion.ToString(),
                runtime = System.Runtime.InteropServices.RuntimeInformation.FrameworkDescription,
            };

            Console.WriteLine(JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true }));
            // Return 0 if unlock was attempted and not obviously failing.
            var laf = payload.laf as IDictionary<string, object?>;
            if (laf != null && laf.TryGetValue("error", out var err) && err != null)
            {
                return 1;
            }
            return 0;
        }

        static async Task<int> CheckAvailability(Dictionary<string, string> opts)
        {
            try
            {
                // Best-effort: attempt LAF unlock first (if configured)
                _ = BuildLafReport(opts);

                var state = LanguageModel.GetReadyState();
                Console.WriteLine(state == AIFeatureReadyState.Ready ? "AVAILABLE" : "NOT_AVAILABLE");
                return state == AIFeatureReadyState.Ready ? 0 : 1;
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine($"ERROR: {ex.Message}");
                return 1;
            }
        }

        static async Task<int> GetModelInfo(Dictionary<string, string> opts)
        {
            try
            {
                var laf = BuildLafReport(opts);
                var state = LanguageModel.GetReadyState();
                var info = new
                {
                    model = "phi-silica",
                    provider = "windows-ai",
                    available = state == AIFeatureReadyState.Ready,
                    readyState = state.ToString(),
                    laf,
                    platform = Environment.OSVersion.ToString(),
                    runtime = System.Runtime.InteropServices.RuntimeInformation.FrameworkDescription
                };

                Console.WriteLine(JsonSerializer.Serialize(info, new JsonSerializerOptions
                {
                    WriteIndented = true
                }));
                return 0;
            }
            catch (UnauthorizedAccessException)
            {
                Console.WriteLine(JsonSerializer.Serialize(new
                {
                    model = "phi-silica",
                    provider = "windows-ai",
                    available = false,
                    error = "Limited Access Feature - requires unlock token",
                    laf = BuildLafReport(opts),
                    platform = Environment.OSVersion.ToString(),
                    runtime = System.Runtime.InteropServices.RuntimeInformation.FrameworkDescription,
                    docs = new
                    {
                        phi_silica = "https://learn.microsoft.com/windows/ai/apis/phi-silica",
                        troubleshooting = "https://learn.microsoft.com/windows/ai/apis/troubleshooting",
                        unlock_shortlink = "https://aka.ms/phi-silica-unlock",
                        laf_request_form = "https://go.microsoft.com/fwlink/?linkid=2271232&c1cid=04x409",
                    },
                }, new JsonSerializerOptions { WriteIndented = true }));
                return 1;
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine($"ERROR: {ex.Message}");
                return 1;
            }
        }

        static async Task<int> GenerateText(string prompt)
        {
            try
            {
                // For generation we only support env-based LAF config.
                var envOpts = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                var (featureId, token, attestation, present) = GetLafConfig(envOpts);
                
                // Attempt LAF unlock if configured, and keep the result alive
                LimitedAccessFeatureRequestResult? lafResult = null;
                if (present && !string.IsNullOrWhiteSpace(featureId) && !string.IsNullOrWhiteSpace(token) && !string.IsNullOrWhiteSpace(attestation))
                {
                    try
                    {
                        lafResult = LimitedAccessFeatures.TryUnlockFeature(featureId, token, attestation);
                        Console.Error.WriteLine($"[PhiSilica] LAF unlock attempted: {lafResult.Status}");
                    }
                    catch (Exception ex)
                    {
                        Console.Error.WriteLine($"[PhiSilica] LAF unlock failed: {ex.Message}");
                    }
                }

                // Check if model is ready
                if (LanguageModel.GetReadyState() == AIFeatureReadyState.NotReady)
                {
                    Console.Error.WriteLine("[PhiSilica] Model not ready, initializing...");
                    await LanguageModel.EnsureReadyAsync();
                }

                Console.Error.WriteLine("[PhiSilica] Creating model...");
                using var languageModel = await LanguageModel.CreateAsync();

                Console.Error.WriteLine("[PhiSilica] Generating response...");
                var result = await languageModel.GenerateResponseAsync(prompt);

                Console.WriteLine(result.Text);
                
                // Keep LAF result alive until we're done
                if (lafResult != null)
                {
                    GC.KeepAlive(lafResult);
                }
                
                return 0;
            }
            catch (UnauthorizedAccessException)
            {
                Console.Error.WriteLine("ERROR: UnauthorizedAccessException (Phi Silica access denied)");
                Console.Error.WriteLine("This usually means Phi Silica is gated by Limited Access Features (LAF) or your app needs package identity + systemAIModels capability.");
                Console.Error.WriteLine("Docs: https://learn.microsoft.com/windows/ai/apis/troubleshooting");
                Console.Error.WriteLine("Request LAF token: https://go.microsoft.com/fwlink/?linkid=2271232&c1cid=04x409");
                return 1;
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine($"ERROR: {ex.Message}");

                // Provide helpful message for common errors
                if (ex.Message.Contains("not found") || ex.Message.Contains("not supported"))
                {
                    Console.Error.WriteLine(@"
Phi Silica requires:
  - Windows 11 Copilot+ PC with NPU
  - Windows App SDK 1.8+
  - Model may need to be downloaded first
");
                }
                return 1;
            }
        }
    }
}


