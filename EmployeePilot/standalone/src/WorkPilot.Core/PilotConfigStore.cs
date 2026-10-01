using System.Text.Json;

namespace WorkPilot.Core;

public static class PilotConfigStore
{
    public static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        PropertyNameCaseInsensitive = true,
        WriteIndented = true
    };

    public static void Save(string path, PilotConfig config)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        File.WriteAllText(path, JsonSerializer.Serialize(config, Json));
    }

    public static PilotConfig? Load(string path)
    {
        if (!File.Exists(path))
        {
            return null;
        }
        return JsonSerializer.Deserialize<PilotConfig>(File.ReadAllText(path), Json);
    }
}
