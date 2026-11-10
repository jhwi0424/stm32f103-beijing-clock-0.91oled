"""Build a single offline CMD installer from reviewable C# source."""
import base64,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
HEADER=r'''@echo off
setlocal DisableDelayedExpansion
set "BJC_PACKAGE=%~f0"
set "BJC_ACTION=%~1"
title STM32 Beijing Clock - Windows USB Auto Sync
echo STM32 Beijing Clock USB Sync - offline installer
echo No Python, downloads, or administrator rights required.
echo First installation may take a moment. Keep this window open.
echo.
%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoLogo -NoProfile -NonInteractive -Command "$ErrorActionPreference='Stop'; $code=1; $tmp=$null; try { $marker='::BJC_PAYLOAD_V1::'; $text=[IO.File]::ReadAllText($env:BJC_PACKAGE); $payload=$text.Substring($text.LastIndexOf($marker)+$marker.Length); $source=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($payload)); $tmp=Join-Path ([IO.Path]::GetTempPath()) ('BeijingClockSetup-'+[Guid]::NewGuid().ToString('N')); [IO.Directory]::CreateDirectory($tmp)|Out-Null; $exe=Join-Path $tmp 'BeijingClockSync.exe'; Add-Type -TypeDefinition $source -Language CSharp -OutputAssembly $exe -OutputType WindowsApplication -ReferencedAssemblies 'System.dll','System.Core.dll'; $action='--install'; if($env:BJC_ACTION -eq '/uninstall'){$action='--uninstall'}; if($env:BJC_ACTION -eq '/test'){$action='--self-test'}; $p=Start-Process -FilePath $exe -ArgumentList $action -WindowStyle Hidden -Wait -PassThru; $code=$p.ExitCode; $result=Join-Path $tmp 'setup-result.txt'; $errorFile=Join-Path $tmp 'setup-error.txt'; if(Test-Path -LiteralPath $result){[Console]::WriteLine([IO.File]::ReadAllText($result))}; if(Test-Path -LiteralPath $errorFile){[Console]::Error.WriteLine([IO.File]::ReadAllText($errorFile))} } catch {[Console]::Error.WriteLine($_.ToString()); $code=1} finally { if($tmp){foreach($name in @('BeijingClockSync.exe','setup-result.txt','setup-error.txt')){$file=Join-Path $tmp $name; if(Test-Path -LiteralPath $file){Remove-Item -LiteralPath $file -Force -ErrorAction SilentlyContinue}}; if(Test-Path -LiteralPath $tmp){Remove-Item -LiteralPath $tmp -ErrorAction SilentlyContinue}} }; exit $code"
set "BJC_RESULT=%ERRORLEVEL%"
echo.
if "%BJC_RESULT%"=="0" (echo Completed.) else (echo Installation failed. See the message above.)
if /I not "%~2"=="/quiet" pause
exit /b %BJC_RESULT%
::BJC_PAYLOAD_V1::
'''
def build():
    source=(ROOT/'windows/BeijingClockSync.cs').read_bytes()
    encoded=base64.b64encode(source).decode('ascii')
    header=HEADER.replace("Add-Type -TypeDefinition $source", "Write-Host '[1/3] Preparing the Windows program...'; Add-Type -TypeDefinition $source")
    header=header.replace("$p=Start-Process -FilePath $exe", "Write-Host '[2/3] Installing and checking startup...'; $p=Start-Process -FilePath $exe")
    header=header.replace("$code=$p.ExitCode; $result", "$code=$p.ExitCode; if($code -eq 0){Write-Host '[3/3] Verification completed.'}; $result")
    body=header+'\n'.join(encoded[i:i+120] for i in range(0,len(encoded),120))+'\n'
    target=ROOT/'dist/Install-BeijingClock.cmd';target.parent.mkdir(exist_ok=True)
    target.write_bytes(body.replace('\r\n','\n').replace('\n','\r\n').encode('ascii'))
    # Keep the original double-click entry point identical, so existing users upgrade safely.
    (ROOT/'install_usb_autosync.cmd').write_bytes(target.read_bytes())
    manifest={'version':'2.0.2','installer_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'source_sha256':hashlib.sha256(source).hexdigest(),'runtime':'Windows PowerShell + .NET Framework; AnyCPU; no Python or network'}
    (target.parent/'windows-package.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print(f'{target.name}: {target.stat().st_size} bytes; SHA256 {manifest["installer_sha256"]}')
    return target
if __name__=='__main__':build()
