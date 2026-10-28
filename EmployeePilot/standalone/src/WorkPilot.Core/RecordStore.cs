namespace WorkPilot.Core;

public static class RecordStore
{
    public static int Clear(string journal, string days, string reports, string liveFile)
    {
        var removed = 0;
        removed += DeleteFiles(journal);
        removed += DeleteFiles(days);
        removed += DeleteFiles(reports);
        removed += DeleteFile(liveFile);
        return removed;
    }

    private static int DeleteFiles(string folder)
    {
        if (!Directory.Exists(folder))
        {
            return 0;
        }
        var removed = 0;
        foreach (var file in Directory.GetFiles(folder))
        {
            removed += DeleteFile(file);
        }
        return removed;
    }

    private static int DeleteFile(string path)
    {
        try
        {
            if (!File.Exists(path))
            {
                return 0;
            }
            File.Delete(path);
            return 1;
        }
        catch (IOException)
        {
            return 0;
        }
        catch (UnauthorizedAccessException)
        {
            return 0;
        }
    }
}
