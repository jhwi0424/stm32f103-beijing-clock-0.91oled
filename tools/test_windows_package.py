"""Exercise the actual offline CMD and native installer in isolated directories."""
import base64,json,os,shutil,struct,subprocess,time,unittest
from pathlib import Path
from build_windows_package import build,ROOT

def powershell(code):
    return subprocess.run(['powershell.exe','-NoLogo','-NoProfile','-NonInteractive','-Command',code],capture_output=True,text=True,encoding='utf-8',errors='replace')
def psquote(path):return "'"+str(path).replace("'","''")+"'"
class WindowsPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.package=build()
        cls.folder=ROOT/'build/windows-package-tests'
        cls.folder.mkdir(parents=True,exist_ok=True)
        cls.exe=cls.folder/'BeijingClockSync.exe'
        if cls.exe.exists():cls.exe.unlink()
        result=powershell(f'Add-Type -Path {psquote(ROOT/"windows/BeijingClockSync.cs")} -OutputAssembly {psquote(cls.exe)} -OutputType WindowsApplication -ReferencedAssemblies System.dll,System.Core.dll')
        if result.returncode:raise RuntimeError(result.stdout+result.stderr)
    def app(self,*args):
        result=subprocess.run([str(self.exe),*map(str,args)],timeout=20)
        error=self.folder/'setup-error.txt'
        self.assertEqual(result.returncode,0,error.read_text(encoding='utf-8') if error.exists() else 'native app failed')
    def test_01_payload_matches_source(self):
        content=self.package.read_text(encoding='ascii')
        payload=content.rsplit('::BJC_PAYLOAD_V1::',1)[1]
        self.assertEqual(base64.b64decode(payload),(ROOT/'windows/BeijingClockSync.cs').read_bytes())
        self.assertEqual(self.package.read_bytes(),(ROOT/'install_usb_autosync.cmd').read_bytes())
    def test_02_protocol_and_enumeration(self):
        self.app('--self-test')
        self.assertIn('SELF_TEST_PASS',(self.folder/'setup-result.txt').read_text(encoding='utf-8'))
    def test_03_anycpu(self):
        data=self.exe.read_bytes();pe=struct.unpack_from('<I',data,0x3c)[0]
        machine=struct.unpack_from('<H',data,pe+4)[0]
        self.assertEqual(machine,0x14c)
        optional=pe+24;magic=struct.unpack_from('<H',data,optional)[0]
        self.assertEqual(magic,0x10b)
        cli_rva=struct.unpack_from('<I',data,optional+96+14*8)[0]
        size=struct.unpack_from('<H',data,pe+20)[0];sections=struct.unpack_from('<H',data,pe+6)[0]
        for i in range(sections):
            section=optional+size+i*40
            virtual_size,virtual_address,raw_size,raw_pointer=struct.unpack_from('<IIII',data,section+8)
            if virtual_address<=cli_rva<virtual_address+max(virtual_size,raw_size):
                flags=struct.unpack_from('<I',data,raw_pointer+cli_rva-virtual_address+16)[0];break
        else:self.fail('CLR header missing')
        self.assertTrue(flags&1,'ILONLY missing')
        self.assertFalse(flags&2,'32BITREQUIRED would break AnyCPU')
        self.assertFalse(flags&0x20000,'32BITPREFERRED unexpectedly set')
    def test_04_install_upgrade_uninstall_unicode_paths(self):
        app=self.folder/"中文 用户 O'Brien & Clock";startup=self.folder/'登录启动 测试'
        self.app('--install','--install-root',app,'--startup-dir',startup,'--no-start')
        installed=app/'BeijingClockSync.exe';link=startup/'STM32 Beijing Clock USB Sync.lnk'
        self.assertEqual(installed.read_bytes(),self.exe.read_bytes());self.assertTrue(link.exists())
        r=powershell(f'$s=(New-Object -ComObject WScript.Shell).CreateShortcut({psquote(link)}); [Console]::WriteLine([Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($s.TargetPath))); [Console]::WriteLine([Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($s.Arguments)))')
        self.assertEqual(r.returncode,0,r.stderr)
        # Base64 avoids dependence on the user's console code page; no pywin32 needed.
        lines=r.stdout.splitlines()
        self.assertEqual(Path(base64.b64decode(lines[0]).decode('utf-8')),installed)
        self.assertEqual(base64.b64decode(lines[1] if len(lines)>1 else '').decode('utf-8'),f'--watch --install-root "{app}"')
        self.app('--install','--install-root',app,'--startup-dir',startup,'--no-start')
        self.assertFalse((app/'BeijingClockSync.exe.previous').exists())
        self.app('--uninstall','--install-root',app,'--startup-dir',startup)
        self.assertFalse(link.exists());self.assertFalse(installed.exists())
    def test_05_single_cmd_from_unicode_path(self):
        folder=self.folder/"独立 安装 O'Brien & Test";folder.mkdir(exist_ok=True)
        package=folder/self.package.name;shutil.copyfile(self.package,package)
        env=os.environ.copy()
        # Prove that neither Python nor the repository is needed by the CMD payload.
        env['PATH']=str(Path(os.environ['SystemRoot'])/'System32')
        cmd=f'cmd.exe /d /s /c ""{package}" /test /quiet"'
        result=subprocess.run(cmd,env=env,cwd=folder,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('SELF_TEST_PASS',result.stdout)
    def test_06_x86_runtime(self):
        csc=Path(os.environ['SystemRoot'])/'Microsoft.NET/Framework/v4.0.30319/csc.exe'
        if not csc.exists():self.skipTest('32-bit .NET compiler is not installed')
        folder=self.folder/'x86';folder.mkdir(exist_ok=True);exe=folder/'BeijingClockSync.exe'
        r=subprocess.run([str(csc),'/nologo','/target:winexe','/platform:x86',f'/out:{exe}',str(ROOT/'windows/BeijingClockSync.cs')],capture_output=True,text=True,timeout=20)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        r=subprocess.run([str(exe),'--self-test'],timeout=10)
        self.assertEqual(r.returncode,0)
        self.assertIn('Process bits: 32',(folder/'setup-result.txt').read_text(encoding='utf-8'))
    def test_07_background_start_relocation_single_instance_and_stop(self):
        app=self.folder/'independent runtime';startup=self.folder/'isolated startup'
        log=app/'logs/clock-sync.log'
        previous=log.read_text(encoding='utf-8').count('START version=') if log.exists() else 0
        try:
            self.app('--install','--install-root',app,'--startup-dir',startup)
            for _ in range(40):
                if log.exists() and 'START version=' in log.read_text(encoding='utf-8'):break
                time.sleep(.1)
            text=log.read_text(encoding='utf-8')
            self.assertIn(str(app/'BeijingClockSync.exe'),text)
            # Keep the original compiled source executable unavailable during the login simulation.
            moved=self.exe.with_name('source-executable-unavailable.exe')
            self.exe.rename(moved)
            try:
                r=subprocess.run([str(app/'BeijingClockSync.exe'),'--watch','--install-root',str(app)],timeout=5)
                self.assertEqual(r.returncode,0,'Duplicate instance must exit promptly')
                r=subprocess.run([str(app/'BeijingClockSync.exe'),'--self-test'],timeout=10)
                self.assertEqual(r.returncode,0)
            finally:moved.rename(self.exe)
            time.sleep(.5)
            self.assertEqual(log.read_text(encoding='utf-8').count('START version='),previous+1)
            # A shortcut starts only the copied EXE, with no dependency on the source executable.
            link=startup/'STM32 Beijing Clock USB Sync.lnk'
            r=powershell(f'$p=Start-Process -FilePath {psquote(link)} -PassThru -Wait -WindowStyle Hidden; if($p){{exit $p.ExitCode}}')
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)
            self.assertEqual(log.read_text(encoding='utf-8').count('START version='),previous+1)
        finally:
            self.app('--uninstall','--install-root',app,'--startup-dir',startup)
        self.assertIn('STOP requested',log.read_text(encoding='utf-8'))
        self.assertFalse((app/'BeijingClockSync.exe').exists())

if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(WindowsPackageTests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    report={'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'successful':result.wasSuccessful()}
    (ROOT/'build/windows-package-tests.json').write_text(json.dumps(report,indent=2)+'\n')
    raise SystemExit(0 if result.wasSuccessful() else 1)
