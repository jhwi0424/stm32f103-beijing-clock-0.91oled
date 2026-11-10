// Windows USB clock synchronization. Requires the .NET Framework shipped with Windows.
// Builds as AnyCPU; no Python, third-party assemblies, network, or elevation required.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.IO.Ports;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using Microsoft.Win32;
using Microsoft.Win32.SafeHandles;

namespace BeijingClock {
    // Use the Unicode shell interface directly. WScript.Shell's late-bound setters
    // can reject non-ACP paths on an English Windows installation.
    [ComImport,Guid("00021401-0000-0000-C000-000000000046")]
    class ShellLinkObject { }
    [ComImport,Guid("000214F9-0000-0000-C000-000000000046"),InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IShellLinkW {
        void GetPath([Out,MarshalAs(UnmanagedType.LPWStr)] StringBuilder path,int count,IntPtr findData,uint flags);
        void GetIDList(out IntPtr list);
        void SetIDList(IntPtr list);
        void GetDescription([Out,MarshalAs(UnmanagedType.LPWStr)] StringBuilder text,int count);
        void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string text);
        void GetWorkingDirectory([Out,MarshalAs(UnmanagedType.LPWStr)] StringBuilder path,int count);
        void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string path);
        void GetArguments([Out,MarshalAs(UnmanagedType.LPWStr)] StringBuilder args,int count);
        void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string args);
        void GetHotkey(out short key);
        void SetHotkey(short key);
        void GetShowCmd(out int command);
        void SetShowCmd(int command);
        void GetIconLocation([Out,MarshalAs(UnmanagedType.LPWStr)] StringBuilder path,int count,out int index);
        void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string path,int index);
        void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string path,uint reserved);
        void Resolve(IntPtr window,uint flags);
        void SetPath([MarshalAs(UnmanagedType.LPWStr)] string path);
    }
    public sealed class Device {
        public string Port;
        public string Identity;
    }
    public static class NativePorts {
        [StructLayout(LayoutKind.Sequential)]
        struct Info { public uint Size; public Guid ClassGuid; public uint Instance; public UIntPtr Reserved; }
        [DllImport("setupapi.dll", CharSet=CharSet.Unicode, SetLastError=true)]
        static extern IntPtr SetupDiGetClassDevs(ref Guid guid, string enumerator, IntPtr parent, uint flags);
        [DllImport("setupapi.dll", SetLastError=true)]
        static extern bool SetupDiEnumDeviceInfo(IntPtr set, uint index, ref Info info);
        [DllImport("setupapi.dll", CharSet=CharSet.Unicode, SetLastError=true)]
        static extern bool SetupDiGetDeviceRegistryProperty(IntPtr set, ref Info info, uint property, out uint type, byte[] buffer, uint size, out uint required);
        [DllImport("setupapi.dll", CharSet=CharSet.Unicode, SetLastError=true)]
        static extern bool SetupDiGetDeviceInstanceId(IntPtr set, ref Info info, StringBuilder id, int size, out int required);
        [DllImport("setupapi.dll", SetLastError=true)]
        static extern IntPtr SetupDiOpenDevRegKey(IntPtr set, ref Info info, uint scope, uint profile, uint keyType, uint access);
        [DllImport("setupapi.dll")]
        static extern bool SetupDiDestroyDeviceInfoList(IntPtr set);

        public static List<Device> List() {
            Guid guid = new Guid("4d36e978-e325-11ce-bfc1-08002be10318"); // Ports class
            IntPtr set = SetupDiGetClassDevs(ref guid, null, IntPtr.Zero, 2); // DIGCF_PRESENT
            if (set == new IntPtr(-1)) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
            var result = new List<Device>();
            try {
                for (uint i = 0; ; i++) {
                    Info info = new Info(); info.Size = (uint)Marshal.SizeOf(typeof(Info));
                    if (!SetupDiEnumDeviceInfo(set, i, ref info)) {
                        int error = Marshal.GetLastWin32Error();
                        if (error == 259) break;
                        throw new System.ComponentModel.Win32Exception(error);
                    }
                    byte[] bytes = new byte[4096]; uint kind, needed;
                    if (!SetupDiGetDeviceRegistryProperty(set, ref info, 1, out kind, bytes, (uint)bytes.Length, out needed)) continue;
                    string ids = Encoding.Unicode.GetString(bytes, 0, (int)Math.Min(needed, (uint)bytes.Length));
                    if (ids.IndexOf("VID_1209&PID_B103", StringComparison.OrdinalIgnoreCase) < 0) continue;
                    IntPtr key = SetupDiOpenDevRegKey(set, ref info, 1, 0, 1, 0x20019);
                    if (key == new IntPtr(-1)) continue;
                    try {
                        using (var safe = new SafeRegistryHandle(key, true))
                        using (var registry = RegistryKey.FromHandle(safe)) {
                            string port = registry.GetValue("PortName") as string;
                            if (String.IsNullOrEmpty(port) || !port.StartsWith("COM", StringComparison.OrdinalIgnoreCase)) continue;
                            StringBuilder id = new StringBuilder(1024); int length;
                            string identity = SetupDiGetDeviceInstanceId(set, ref info, id, id.Capacity, out length) ? id.ToString() : port;
                            result.Add(new Device { Port = port, Identity = identity + "|" + port });
                        }
                    } catch (IOException) { } catch (UnauthorizedAccessException) { }
                }
            } finally { SetupDiDestroyDeviceInfoList(set); }
            return result;
        }
    }

    public static class Protocol {
        public static long UtcMilliseconds() { return (DateTime.UtcNow.Ticks - 621355968000000000L) / 10000; }
        public static byte[] Frame(long timestamp) {
            uint seconds = checked((uint)(timestamp / 1000)); uint ms = (uint)(timestamp % 1000);
            byte[] b = new byte[16]; b[0]=66; b[1]=74; b[2]=84; b[3]=49;
            Put(b, 4, seconds); Put(b, 8, ms); Put(b, 12, seconds ^ ms ^ 0x314a5442u);
            return b;
        }
        static void Put(byte[] b, int offset, uint value) {
            for (int i=0;i<4;i++) b[offset+i]=(byte)(value>>(8*i));
        }
        public static uint[] Parse(string line) {
            string[] fields = line.Trim().Split(new char[]{' '}, StringSplitOptions.RemoveEmptyEntries);
            if (fields.Length != 5 || fields[0] != "BJT1") throw new IOException("Device signature did not match BJT1.");
            uint[] values = new uint[4];
            for(int i=0;i<4;i++)
                if(!UInt32.TryParse(fields[i+1],NumberStyles.None,CultureInfo.InvariantCulture,out values[i]))
                    throw new IOException("Invalid clock response field.");
            // Zero is permitted before the board's first synchronization.
            if(values[1]>=1000 || (values[2]!=1 && values[2]!=3)) throw new IOException("Invalid RTC response.");
            return values;
        }
    }

    public static class App {
        // Scope control signals to the installation, so isolated tests cannot stop production.
        static string Scope {
            get {
                using(var hash=System.Security.Cryptography.SHA256.Create())
                    return BitConverter.ToString(hash.ComputeHash(Encoding.UTF8.GetBytes(Path.GetFullPath(Root).ToUpperInvariant())),0,8).Replace("-","");
            }
        }
        static string MutexName {get{return "Local\\STM32BeijingClockUSBWatcherV2_"+Scope;}}
        static string StopName {get{return "Local\\STM32BeijingClockStopV2_"+Scope;}}
        const string ShortcutName="STM32 Beijing Clock USB Sync.lnk";
        static readonly string DefaultRoot=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"STM32BeijingClock");
        static string Root=DefaultRoot;
        static string Startup=Environment.GetFolderPath(Environment.SpecialFolder.Startup);
        static string Self=Assembly.GetExecutingAssembly().Location;
        static readonly object LogLock=new object();

        static void Log(string message) {
            try { lock(LogLock) {
                string folder=Path.Combine(Root,"logs");Directory.CreateDirectory(folder);
                string path=Path.Combine(folder,"clock-sync.log");
                if(File.Exists(path) && new FileInfo(path).Length>512000) {
                    if(File.Exists(path+".1"))File.Delete(path+".1");File.Move(path,path+".1");
                }
                File.AppendAllText(path,DateTimeOffset.Now.ToString("o")+" "+message+Environment.NewLine,new UTF8Encoding(false));
            } } catch(IOException) { } catch(UnauthorizedAccessException) { }
        }
        static uint[] Query(SerialPort port) { port.Write("INFO\n");return Protocol.Parse(port.ReadLine()); }
        public static void Sync(string name) {
            using(var port=new SerialPort(name,115200,Parity.None,8,StopBits.One)) {
                port.ReadTimeout=1000;port.WriteTimeout=1000;port.NewLine="\n";port.DtrEnable=true;port.RtsEnable=false;
                port.Open();port.DiscardInBuffer();uint[] before=Query(port);
                byte[] frame=Protocol.Frame(Protocol.UtcMilliseconds());port.Write(frame,0,frame.Length);
                uint[] after=Protocol.Parse(port.ReadLine());
                long device=(long)after[0]*1000+after[1];
                if(after[3]!=unchecked(before[3]+1) || Math.Abs(device-Protocol.UtcMilliseconds())>1000)
                    throw new IOException("Clock did not acknowledge synchronization.");
                DateTime bjt=new DateTime(1970,1,1,0,0,0,DateTimeKind.Utc).AddMilliseconds(device).AddHours(8);
                Log("SYNC_OK "+name+" Beijing="+bjt.ToString("yyyy-MM-dd HH:mm:ss.fff",CultureInfo.InvariantCulture)+" source="+after[2]+" count="+after[3]);
            }
        }
        static int Watch(bool once) {
            bool created;
            using(var mutex=new Mutex(true,MutexName,out created)) {
                if(!created)return 0;
                try {
                    using(var stop=new EventWaitHandle(false,EventResetMode.ManualReset,StopName)) {
                        var synchronized=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                        var warning=new Dictionary<string,long>(StringComparer.OrdinalIgnoreCase);
                        var watch=Stopwatch.StartNew();
                        Log("START version=2.0.2 executable="+Self);
                        do {
                            List<Device> ports;
                            try { ports=NativePorts.List(); }
                            catch(Exception e) { Log("ENUM_RETRY "+e.Message);if(once)return 2;stop.WaitOne(1000);continue; }
                            var present=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                            foreach(Device device in ports)present.Add(device.Identity);
                            synchronized.RemoveWhere(delegate(string id){return !present.Contains(id);});
                            var gone=new List<string>();foreach(string id in warning.Keys)if(!present.Contains(id))gone.Add(id);
                            foreach(string id in gone)warning.Remove(id);
                            foreach(Device device in ports) {
                                if(synchronized.Contains(device.Identity))continue;
                                try { Sync(device.Port);synchronized.Add(device.Identity);warning.Remove(device.Identity); }
                                catch(Exception e) {
                                    long last;
                                    if(!warning.TryGetValue(device.Identity,out last) || watch.ElapsedMilliseconds-last>30000) {
                                        Log("SYNC_RETRY "+device.Port+" "+e.Message);warning[device.Identity]=watch.ElapsedMilliseconds;
                                    }
                                }
                            }
                            if(once)return synchronized.Count>0?0:2;
                        } while(!stop.WaitOne(250));
                        Log("STOP requested");
                    }
                } finally {mutex.ReleaseMutex();}
            }
            return 0;
        }
        static void StopNamed(string eventName,string mutexName) {
            try {using(var stop=EventWaitHandle.OpenExisting(eventName))stop.Set();}
            catch(WaitHandleCannotBeOpenedException) {return;}
            for(int i=0;i<60;i++) {
                try {using(var m=Mutex.OpenExisting(mutexName)) {}}
                catch(WaitHandleCannotBeOpenedException) {return;}
                Thread.Sleep(100);
            }
            throw new IOException("The previous watcher is still running; close it or sign out before upgrading.");
        }
        static void Stop() {StopNamed(StopName,MutexName);}
        static void StopLegacy() {
            if(String.Equals(Path.GetFullPath(Root),Path.GetFullPath(DefaultRoot),StringComparison.OrdinalIgnoreCase))
                StopNamed("Local\\STM32BeijingClockStopV2","Local\\STM32BeijingClockUSBWatcherV2");
        }
        static void Shortcut(string path,string target) {
            object obj=new ShellLinkObject();
            try {
                var link=(IShellLinkW)obj;
                link.SetPath(target);link.SetArguments("--watch --install-root \""+Root+"\"");
                link.SetWorkingDirectory(Path.GetDirectoryName(target));
                link.SetDescription("Synchronize the STM32 clock once on each USB connection.");link.SetShowCmd(7);
                ((System.Runtime.InteropServices.ComTypes.IPersistFile)obj).Save(path,true);
                if(!File.Exists(target) || !File.Exists(path))
                    throw new IOException("Startup shortcut verification failed.");
            } finally {Marshal.FinalReleaseComObject(obj);}
            string[] saved=ReadShortcut(path);
            if(!String.Equals(saved[0],target,StringComparison.OrdinalIgnoreCase))throw new IOException("Saved startup target did not match.");
        }
        static string[] ReadShortcut(string path) {
            object obj=new ShellLinkObject();
            try {
                ((System.Runtime.InteropServices.ComTypes.IPersistFile)obj).Load(path,0);
                var link=(IShellLinkW)obj;var target=new StringBuilder(32768);var args=new StringBuilder(32768);
                link.GetPath(target,target.Capacity,IntPtr.Zero,4); // SLGP_RAWPATH: do not resolve under a different user.
                link.GetArguments(args,args.Capacity);
                return new string[]{target.ToString(),args.ToString()};
            } finally {Marshal.FinalReleaseComObject(obj);}
        }
        static void SafeRoot(string value) {
            string full=Path.GetFullPath(value).TrimEnd(Path.DirectorySeparatorChar);
            if(full.Length<5 || String.Equals(full,Path.GetPathRoot(full).TrimEnd(Path.DirectorySeparatorChar),StringComparison.OrdinalIgnoreCase))
                throw new IOException("Invalid installation directory.");
        }
        static void Install(bool launch) {
            SafeRoot(Root);Directory.CreateDirectory(Root);Directory.CreateDirectory(Startup);
            string target=Path.Combine(Root,"BeijingClockSync.exe");
            string next=target+".new";string backup=target+".previous";
            string shortcut=Path.Combine(Startup,ShortcutName);string pending=Path.Combine(Startup,"STM32 Beijing Clock USB Sync.pending.lnk");
            bool different=!String.Equals(Path.GetFullPath(Self),Path.GetFullPath(target),StringComparison.OrdinalIgnoreCase);
            StopLegacy();Stop();
            if(different) {
                File.Copy(Self,next,true);
                if(File.Exists(target))File.Replace(next,target,backup,true);else File.Move(next,target);
            }
            try {
                Shortcut(pending,target);
                if(File.Exists(shortcut))File.Replace(pending,shortcut,null,true);else File.Move(pending,shortcut);
            } catch {
                if(different && File.Exists(backup))File.Copy(backup,target,true);
                throw;
            } finally {if(File.Exists(pending))File.Delete(pending);}
            if(File.Exists(backup))File.Delete(backup);
            if(launch) {
                Process.Start(new ProcessStartInfo(target){Arguments="--watch --install-root \""+Root+"\"",WorkingDirectory=Root,UseShellExecute=false,CreateNoWindow=true,WindowStyle=ProcessWindowStyle.Hidden});
                bool ready=false;
                for(int i=0;i<50;i++) {
                    try {using(var m=Mutex.OpenExisting(MutexName)) {ready=true;break;}}
                    catch(WaitHandleCannotBeOpenedException) {Thread.Sleep(100);}
                }
                if(!ready)throw new IOException("Installed, but the background watcher did not start. Check the log folder.");
            }
            Result("Installed successfully.\r\nProgram: "+target+"\r\nStartup: "+shortcut+"\r\nLogs: "+Path.Combine(Root,"logs")+"\r\nPython and the original package are no longer required.");
            Log("INSTALL_OK startup="+shortcut);
        }
        static void Uninstall() {
            SafeRoot(Root);StopLegacy();Stop();string shortcut=Path.Combine(Startup,ShortcutName);
            if(File.Exists(shortcut))File.Delete(shortcut);
            string target=Path.Combine(Root,"BeijingClockSync.exe");
            if(File.Exists(target) && !String.Equals(Path.GetFullPath(Self),Path.GetFullPath(target),StringComparison.OrdinalIgnoreCase))File.Delete(target);
            Result("Automatic startup disabled; watcher stopped. Logs retained in "+Path.Combine(Root,"logs"));
        }
        static void Result(string text) {File.WriteAllText(Path.Combine(Path.GetDirectoryName(Self),"setup-result.txt"),text,new UTF8Encoding(false));}
        static void SelfTest() {
            byte[] frame=Protocol.Frame(1704067200123L);
            if(frame.Length!=16 || Encoding.ASCII.GetString(frame,0,4)!="BJT1" || BitConverter.ToUInt32(frame,4)!=1704067200u || BitConverter.ToUInt32(frame,8)!=123u || BitConverter.ToUInt32(frame,12)!=(1704067200u^123u^0x314a5442u))throw new Exception("Packet serialization failed.");
            uint[] v=Protocol.Parse("BJT1 1704067200 999 1 7\n");if(v[1]!=999 || v[3]!=7)throw new Exception("Parser failed.");
            string[] invalid={"OTHER 1 2 1 1","BJT1 1 1000 1 1","BJT1 1 0 2 1","BJT1 -1 0 1 1","BJT1 1 0 1 1 extra"};
            foreach(string line in invalid) {bool rejected=false;try {Protocol.Parse(line);}catch(IOException){rejected=true;}if(!rejected)throw new Exception("Invalid reply accepted.");}
            var text=new StringBuilder("SELF_TEST_PASS\r\nOS: "+Environment.OSVersion+"\r\nCLR: "+Environment.Version+"\r\nProcess bits: "+(IntPtr.Size*8)+"\r\n");
            foreach(Device d in NativePorts.List())text.AppendLine("Clock: "+d.Port);
            Result(text.ToString());
        }
        [STAThread]
        public static int Main(string[] args) {
            try {
                bool launch=true;string action="--watch",shortcutToInspect=null;
                for(int i=0;i<args.Length;i++) {
                    if(args[i]=="--install-root" && i+1<args.Length)Root=Path.GetFullPath(args[++i]);
                    else if(args[i]=="--startup-dir" && i+1<args.Length)Startup=Path.GetFullPath(args[++i]);
                    else if(args[i]=="--no-start")launch=false;
                    else if(args[i]=="--shortcut" && i+1<args.Length)shortcutToInspect=args[++i];
                    else action=args[i];
                }
                if(action=="--install") {Install(launch);return 0;}
                if(action=="--uninstall") {Uninstall();return 0;}
                if(action=="--stop") {Stop();return 0;}
                if(action=="--self-test") {SelfTest();return 0;}
                if(action=="--inspect-shortcut") {
                    string[] saved=ReadShortcut(shortcutToInspect);
                    Result(Convert.ToBase64String(Encoding.UTF8.GetBytes(saved[0]))+Environment.NewLine+Convert.ToBase64String(Encoding.UTF8.GetBytes(saved[1])));return 0;
                }
                if(action=="--once")return Watch(true);
                if(action=="--watch")return Watch(false);
                throw new ArgumentException("Unknown action: "+action);
            } catch(Exception e) {
                Log("ERROR "+e);
                try {File.WriteAllText(Path.Combine(Path.GetDirectoryName(Self),"setup-error.txt"),e.ToString(),new UTF8Encoding(false));}catch { }
                return 1;
            }
        }
    }
}
