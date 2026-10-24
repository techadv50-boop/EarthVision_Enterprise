using System.Runtime.InteropServices;

namespace WorkPilot.Windows;

internal static class WindowsAccount
{
    public static bool Exists(string userName)
    {
        var code = NetUserGetInfo(null, userName, 0, out var buffer);
        if (buffer != IntPtr.Zero)
        {
            NetApiBufferFree(buffer);
        }
        return code == 0;
    }

    public static void Create(string userName, string password, string fullName)
    {
        var info = new UserInfo1
        {
            Name = userName,
            Password = password,
            Priv = 1,
            Comment = "WorkPilot pilot employee",
            Flags = 0x0001 | 0x0200 | 0x10000
        };
        var code = NetUserAdd(null, 1, ref info, out _);
        if (code != 0)
        {
            throw new InvalidOperationException(Message(code));
        }
        SetFullName(userName, fullName);
    }

    public static void SetFullName(string userName, string fullName)
    {
        var info = new UserInfo1011 { FullName = fullName };
        var code = NetUserSetInfo(null, userName, 1011, ref info, out _);
        if (code != 0)
        {
            throw new InvalidOperationException(Message(code));
        }
    }

    public static void AddToGroup(string userName, string group)
    {
        if (!TryAddToGroup(userName, group, out var error))
        {
            throw new InvalidOperationException(error);
        }
    }

    public static bool TryAddToGroup(string userName, string group, out string error)
    {
        var member = new LocalGroupMember { DomainAndName = Environment.MachineName + "\\" + userName };
        var code = NetLocalGroupAddMembers(null, group, 3, ref member, 1);
        error = code is 0 or 1378 ? "" : $"Could not add the login to {group}. {Message(code)}";
        return code is 0 or 1378;
    }

    public static void RemoveFromGroup(string userName, string group)
    {
        var member = new LocalGroupMember { DomainAndName = Environment.MachineName + "\\" + userName };
        var code = NetLocalGroupDelMembers(null, group, 3, ref member, 1);
        if (code is not (0 or 1377))
        {
            throw new InvalidOperationException(Message(code));
        }
    }

    private static string Message(int code) => code switch
    {
        5 => "Windows blocked the new login. Approve the administrator prompt and try again.",
        2203 or 86 => "Windows rejected that password. Choose a different one.",
        2245 => "Windows wants a stronger password. Use a longer password with a capital letter, a small letter, and a number.",
        _ => "Windows could not finish the login. Error " + code
    };

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct UserInfo1
    {
        public string Name;
        public string Password;
        public int PasswordAge;
        public int Priv;
        public string? HomeDir;
        public string Comment;
        public int Flags;
        public string? ScriptPath;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct UserInfo1011
    {
        public string FullName;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct LocalGroupMember
    {
        public string DomainAndName;
    }

    [DllImport("netapi32.dll", CharSet = CharSet.Unicode)]
    private static extern int NetUserGetInfo(string? serverName, string userName, int level, out IntPtr buffer);

    [DllImport("netapi32.dll", CharSet = CharSet.Unicode)]
    private static extern int NetUserAdd(string? serverName, int level, ref UserInfo1 userInfo, out int parmError);

    [DllImport("netapi32.dll", CharSet = CharSet.Unicode)]
    private static extern int NetUserSetInfo(string? serverName, string userName, int level, ref UserInfo1011 userInfo, out int parmError);

    [DllImport("netapi32.dll", CharSet = CharSet.Unicode)]
    private static extern int NetLocalGroupAddMembers(string? serverName, string groupName, int level, ref LocalGroupMember member, int totalEntries);

    [DllImport("netapi32.dll", CharSet = CharSet.Unicode)]
    private static extern int NetLocalGroupDelMembers(string? serverName, string groupName, int level, ref LocalGroupMember member, int totalEntries);

    [DllImport("netapi32.dll")]
    private static extern int NetApiBufferFree(IntPtr buffer);
}
