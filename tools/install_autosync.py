"""Compatibility entry point: use the standalone Windows installer, never Python paths."""
from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    raise SystemExit(subprocess.call(f'cmd.exe /d /s /c ""{ROOT / "install_usb_autosync.cmd"}" /install /quiet"',cwd=ROOT))
