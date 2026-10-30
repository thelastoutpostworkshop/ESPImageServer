using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

namespace EspImageServer.Setup
{
    // Own the entire bootstrap tree. Starting suspended closes the race where
    // pip/winget could create children before their parent joins the job.
    public sealed class BootstrapProcess : IDisposable
    {
        private IntPtr job;
        private IntPtr process;
        public uint ProcessId { get; private set; }

        private BootstrapProcess() { }

        public static BootstrapProcess Start(string executable, string[] arguments, string directory)
        {
            BootstrapProcess owner = new BootstrapProcess();
            PROCESS_INFORMATION info = new PROCESS_INFORMATION();
            bool assigned = false;
            try
            {
                owner.job = CreateJobObject(IntPtr.Zero, null);
                if (owner.job == IntPtr.Zero) throw NativeError("Create bootstrap job");
                JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
                limits.BasicLimitInformation.LimitFlags = 0x00002000; // KILL_ON_JOB_CLOSE
                if (!SetInformationJobObject(owner.job, 9, ref limits,
                    (uint)Marshal.SizeOf(typeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION))))
                    throw NativeError("Configure bootstrap job");

                STARTUPINFO startup = new STARTUPINFO();
                startup.cb = (uint)Marshal.SizeOf(typeof(STARTUPINFO));
                startup.dwFlags = 1; // STARTF_USESHOWWINDOW
                startup.wShowWindow = 0; // SW_HIDE
                StringBuilder command = new StringBuilder(QuoteArgument(executable));
                foreach (string argument in arguments) command.Append(" ").Append(QuoteArgument(argument));
                if (!CreateProcess(executable, command, IntPtr.Zero, IntPtr.Zero, false,
                    0x08000004, IntPtr.Zero, directory, ref startup, out info)) // NO_WINDOW | SUSPENDED
                    throw NativeError("Start bootstrap PowerShell");
                owner.process = info.hProcess;
                owner.ProcessId = info.dwProcessId;
                if (!AssignProcessToJobObject(owner.job, owner.process))
                    throw NativeError("Assign bootstrap PowerShell to its job");
                assigned = true;
                if (ResumeThread(info.hThread) == UInt32.MaxValue)
                    throw NativeError("Resume bootstrap PowerShell");
                return owner;
            }
            catch (Exception startError)
            {
                // An unassigned process is still suspended and has no children.
                // Closing our job cannot terminate it, so handle that case here.
                try
                {
                    if (assigned)
                    {
                        owner.TerminateAndWait(10000);
                    }
                    else if (owner.process != IntPtr.Zero &&
                        WaitForSingleObject(owner.process, 0) != 0)
                    {
                        if (!TerminateProcess(owner.process, 1))
                            throw NativeError("Stop unassigned bootstrap PowerShell");
                        if (WaitForSingleObject(owner.process, 10000) != 0)
                            throw new TimeoutException("Unassigned bootstrap PowerShell did not stop.");
                    }
                }
                catch (Exception cleanupError)
                {
                    throw new InvalidOperationException(startError.Message +
                        " Bootstrap startup cleanup failed: " + cleanupError.Message, startError);
                }
                finally { owner.Dispose(); }
                throw;
            }
            finally
            {
                if (info.hThread != IntPtr.Zero) CloseHandle(info.hThread);
            }
        }

        public bool HasExited
        {
            get
            {
                uint state = WaitForSingleObject(process, 0);
                if (state == 0) return true;
                if (state == 258) return false; // WAIT_TIMEOUT
                throw NativeError("Read bootstrap process state");
            }
        }

        public uint ExitCode
        {
            get
            {
                if (!HasExited) throw new InvalidOperationException("Bootstrap is still running.");
                uint code;
                if (!GetExitCodeProcess(process, out code)) throw NativeError("Read bootstrap exit code");
                return code;
            }
        }

        public uint ActiveProcessCount
        {
            get
            {
                JOBOBJECT_BASIC_ACCOUNTING_INFORMATION accounting;
                if (!QueryInformationJobObject(job, 1, out accounting,
                    (uint)Marshal.SizeOf(typeof(JOBOBJECT_BASIC_ACCOUNTING_INFORMATION)), IntPtr.Zero))
                    throw NativeError("Read bootstrap process tree state");
                return accounting.ActiveProcesses;
            }
        }

        public void TerminateAndWait(int timeoutMilliseconds)
        {
            if (ActiveProcessCount != 0 && !TerminateJobObject(job, 2))
                throw NativeError("Stop bootstrap process tree");
            Stopwatch deadline = Stopwatch.StartNew();
            while (ActiveProcessCount != 0)
            {
                if (deadline.ElapsedMilliseconds >= timeoutMilliseconds)
                    throw new TimeoutException("The bootstrap process tree did not stop within " +
                        timeoutMilliseconds + " milliseconds.");
                Thread.Sleep(25);
            }
        }

        public void Dispose()
        {
            // KILL_ON_JOB_CLOSE also protects against supervisor crashes and
            // forced termination: Windows closes these non-inherited handles.
            if (job != IntPtr.Zero) { CloseHandle(job); job = IntPtr.Zero; }
            if (process != IntPtr.Zero) { CloseHandle(process); process = IntPtr.Zero; }
        }

        private static Win32Exception NativeError(string operation)
        {
            int code = Marshal.GetLastWin32Error();
            return new Win32Exception(code, operation + ": " + new Win32Exception(code).Message);
        }

        private static string QuoteArgument(string value)
        {
            // Windows native command-line quoting, including trailing backslashes.
            StringBuilder result = new StringBuilder("\"");
            int slashes = 0;
            foreach (char character in value)
            {
                if (character == '\\') { slashes++; continue; }
                if (character == '"')
                {
                    result.Append('\\', slashes * 2 + 1).Append('"');
                    slashes = 0;
                    continue;
                }
                result.Append('\\', slashes).Append(character);
                slashes = 0;
            }
            return result.Append('\\', slashes * 2).Append('"').ToString();
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct STARTUPINFO
        {
            public uint cb;
            public IntPtr lpReserved, lpDesktop, lpTitle;
            public uint dwX, dwY, dwXSize, dwYSize, dwXCountChars, dwYCountChars, dwFillAttribute, dwFlags;
            public ushort wShowWindow, cbReserved2;
            public IntPtr lpReserved2, hStdInput, hStdOutput, hStdError;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct PROCESS_INFORMATION
        {
            public IntPtr hProcess, hThread;
            public uint dwProcessId, dwThreadId;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct JOBOBJECT_BASIC_LIMIT_INFORMATION
        {
            public long PerProcessUserTimeLimit, PerJobUserTimeLimit;
            public uint LimitFlags;
            public UIntPtr MinimumWorkingSetSize, MaximumWorkingSetSize;
            public uint ActiveProcessLimit;
            public UIntPtr Affinity;
            public uint PriorityClass, SchedulingClass;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct IO_COUNTERS
        {
            public ulong ReadOperationCount, WriteOperationCount, OtherOperationCount;
            public ulong ReadTransferCount, WriteTransferCount, OtherTransferCount;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION
        {
            public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
            public IO_COUNTERS IoInfo;
            public UIntPtr ProcessMemoryLimit, JobMemoryLimit, PeakProcessMemoryUsed, PeakJobMemoryUsed;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct JOBOBJECT_BASIC_ACCOUNTING_INFORMATION
        {
            public long TotalUserTime, TotalKernelTime, ThisPeriodTotalUserTime, ThisPeriodTotalKernelTime;
            public uint TotalPageFaultCount, TotalProcesses, ActiveProcesses, TotalTerminatedProcesses;
        }

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern IntPtr CreateJobObject(IntPtr attributes, string name);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool SetInformationJobObject(IntPtr job, int infoClass,
            ref JOBOBJECT_EXTENDED_LIMIT_INFORMATION info, uint length);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool QueryInformationJobObject(IntPtr job, int infoClass,
            out JOBOBJECT_BASIC_ACCOUNTING_INFORMATION info, uint length, IntPtr returnLength);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool CreateProcess(string application, StringBuilder command,
            IntPtr processAttributes, IntPtr threadAttributes, bool inheritHandles, uint flags,
            IntPtr environment, string directory, ref STARTUPINFO startup, out PROCESS_INFORMATION info);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern uint ResumeThread(IntPtr thread);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool GetExitCodeProcess(IntPtr process, out uint exitCode);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool TerminateProcess(IntPtr process, uint exitCode);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool TerminateJobObject(IntPtr job, uint exitCode);
        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool CloseHandle(IntPtr handle);
    }
}
