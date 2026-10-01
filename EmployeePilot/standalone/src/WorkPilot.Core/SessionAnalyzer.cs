namespace WorkPilot.Core;

public static class SessionAnalyzer
{
    public static SessionSummary Summarize(
        IReadOnlyList<ActivitySample> samples,
        int idleThresholdSeconds,
        IReadOnlyList<string>? allowedPrograms = null,
        IReadOnlyList<string>? systemPrograms = null)
    {
        if (idleThresholdSeconds < 1)
        {
            throw new ArgumentOutOfRangeException(nameof(idleThresholdSeconds));
        }

        allowedPrograms ??= Array.Empty<string>();
        systemPrograms ??= Array.Empty<string>();
        var summary = new SessionSummary { IdleThresholdSeconds = idleThresholdSeconds };
        if (samples.Count == 0)
        {
            return summary;
        }

        var points = samples
            .Select(Normalize)
            .OrderBy(point => point.Utc)
            .ThenBy(point => point.Process, StringComparer.Ordinal)
            .ToList();
        summary.SampleCount = points.Count;
        var sessionStart = points[0].Utc;
        var sessionEnd = points[^1].Utc;
        summary.SessionStart = sessionStart;
        summary.SessionEnd = sessionEnd;
        if (sessionEnd <= sessionStart)
        {
            return summary;
        }

        var runningLast = points[0].LastInput;
        var normalized = new List<NormalizedPoint>(points.Count);
        foreach (var point in points)
        {
            if (point.LastInput > runningLast)
            {
                runningLast = point.LastInput;
            }
            normalized.Add(point with { RunningLastInput = runningLast });
        }

        var boundaries = new SortedDictionary<long, DateTime>
        {
            [sessionStart.Ticks] = sessionStart,
            [sessionEnd.Ticks] = sessionEnd
        };
        foreach (var point in normalized)
        {
            var cut = point.LastInput.AddSeconds(idleThresholdSeconds);
            if (cut > sessionStart && cut < sessionEnd)
            {
                boundaries[cut.Ticks] = cut;
            }
            if (point.Utc > sessionStart && point.Utc < sessionEnd)
            {
                boundaries[point.Utc.Ticks] = point.Utc;
            }
        }

        var marks = boundaries.Values.ToList();
        var raw = new List<TimelineSlice>();
        var index = 0;
        for (var i = 0; i < marks.Count - 1; i++)
        {
            var start = marks[i];
            var end = marks[i + 1];
            var seconds = (int)Math.Round((end - start).TotalSeconds);
            if (seconds <= 0)
            {
                continue;
            }
            while (index + 1 < normalized.Count && normalized[index + 1].Utc <= start)
            {
                index++;
            }
            var known = normalized[index];
            string? away = null;
            if (known.Locked)
            {
                away = "Locked";
            }
            else if (start >= known.RunningLastInput.AddSeconds(idleThresholdSeconds))
            {
                away = "Idle";
            }
            raw.Add(new TimelineSlice
            {
                Start = start,
                End = end,
                Seconds = seconds,
                Kind = away ?? "Active",
                Process = away is null ? known.Process : "",
                Title = away is null ? known.Title : ""
            });
        }

        var merged = new List<TimelineSlice>();
        foreach (var slice in raw)
        {
            if (merged.Count == 0)
            {
                merged.Add(slice);
                continue;
            }
            var previous = merged[^1];
            var same = previous.Kind == slice.Kind && previous.Process == slice.Process && previous.Title == slice.Title;
            if (same)
            {
                previous.End = slice.End;
                previous.Seconds += slice.Seconds;
            }
            else
            {
                merged.Add(slice);
            }
        }

        var active = 0;
        var idle = 0;
        var locked = 0;
        var longest = 0;
        var awayRun = 0;
        var programs = new Dictionary<string, ProgramTotal>(StringComparer.OrdinalIgnoreCase);
        foreach (var slice in merged)
        {
            if (slice.Kind == "Active")
            {
                active += slice.Seconds;
                awayRun = 0;
                if (!programs.TryGetValue(slice.Process, out var total))
                {
                    var group = "Outside";
                    if (InList(slice.Process, allowedPrograms))
                    {
                        group = "Allowed";
                    }
                    else if (InList(slice.Process, systemPrograms))
                    {
                        group = "Windows";
                    }
                    total = new ProgramTotal { Process = slice.Process, Group = group };
                    programs[slice.Process] = total;
                }
                total.ActiveSeconds += slice.Seconds;
            }
            else
            {
                idle += slice.Seconds;
                if (slice.Kind == "Locked")
                {
                    locked += slice.Seconds;
                }
                awayRun += slice.Seconds;
                if (awayRun > longest)
                {
                    longest = awayRun;
                }
            }
        }

        var sessionSeconds = (int)Math.Round((sessionEnd - sessionStart).TotalSeconds);
        var ordered = programs.Values.OrderByDescending(item => item.ActiveSeconds).ToList();
        summary.SessionSeconds = sessionSeconds;
        summary.ActiveSeconds = active;
        summary.IdleSeconds = idle;
        summary.LockedSeconds = locked;
        summary.LongestIdleSeconds = longest;
        summary.ActivePercent = sessionSeconds > 0 ? Math.Round(100.0 * active / sessionSeconds, 1) : 0;
        summary.Programs = ordered;
        summary.OutsidePrograms = ordered.Where(item => item.Group == "Outside").ToList();
        summary.Timeline = merged;
        return summary;
    }

    private static NormalizedPoint Normalize(ActivitySample sample)
    {
        var idle = Math.Clamp(sample.IdleSeconds, 0, 604800);
        var utc = sample.Utc.Kind switch
        {
            DateTimeKind.Utc => sample.Utc,
            DateTimeKind.Local => sample.Utc.ToUniversalTime(),
            _ => DateTime.SpecifyKind(sample.Utc, DateTimeKind.Utc)
        };
        var process = Path.GetFileName(sample.Process ?? "");
        if (string.IsNullOrWhiteSpace(process))
        {
            process = "unknown.exe";
        }
        var title = (sample.Title ?? "").Replace('\r', ' ').Replace('\n', ' ').Replace('\t', ' ').Trim();
        if (title.Length > 180)
        {
            title = title[..180];
        }
        return new NormalizedPoint(utc, utc.AddSeconds(-idle), utc, process, title, sample.Locked);
    }

    private static bool InList(string name, IReadOnlyList<string> list)
    {
        var baseName = Path.GetFileName(name);
        foreach (var item in list)
        {
            if (string.Equals(Path.GetFileName(item), baseName, StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }
        }
        return false;
    }

    private sealed record NormalizedPoint(
        DateTime Utc,
        DateTime LastInput,
        DateTime RunningLastInput,
        string Process,
        string Title,
        bool Locked);
}
