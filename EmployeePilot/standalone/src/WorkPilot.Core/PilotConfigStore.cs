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

    public static PilotConfig LoadOrReplace(string path, PilotConfig fallback)
    {
        try
        {
            var loaded = Load(path);
            if (loaded is not null && !string.IsNullOrWhiteSpace(loaded.UserName))
            {
                return loaded;
            }
        }
        catch (JsonException)
        {
            // A damaged setup file is replaced below.
        }
        Save(path, fallback);
        return fallback;
    }
}
