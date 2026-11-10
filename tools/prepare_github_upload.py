"""Prepare a bounded, explicit publish manifest; omit local logs and Git metadata."""
from pathlib import Path
import base64,hashlib,json
ROOT=Path(__file__).resolve().parents[1]
ROOT_FILES=['.gitignore','.gitattributes','LICENSE','README.md','install_usb_autosync.cmd','install_usb_autosync.ps1','uninstall_usb_autosync.ps1','start_usb_sync.cmd','sync_via_stlink.cmd']
def main():
    paths=[ROOT/p for p in ROOT_FILES]
    for folder in ['firmware','tools','windows','docs','.github','vendor/libopencm3-clock']:
        paths.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and not any(x in {'.git','__pycache__','doc','tests'} for x in p.relative_to(ROOT/folder).parts) and p.suffix not in {'.pyc','.o','.d','.lst','.map','.elf'})
    paths.extend([ROOT/'vendor/README.md',ROOT/'dist/Install-BeijingClock.cmd',ROOT/'dist/windows-package.json',ROOT/'dist/firmware/clock.hex',ROOT/'dist/firmware/clock.bin'])
    text=[];binary=[]
    for p in sorted(set(paths)):
        raw=p.read_bytes();path=p.relative_to(ROOT).as_posix()
        if p.suffix in {'.a','.bin'}:
            binary.append({'path':path,'content':base64.b64encode(raw).decode(),'encoding':'base64'})
            continue
        try:content=raw.decode('utf-8')
        except UnicodeDecodeError:
            binary.append({'path':path,'content':base64.b64encode(raw).decode(),'encoding':'base64'});continue
        if p.suffix!='.cmd':content=content.replace('\r\n','\n')
        text.append({'path':path,'mode':'100644','type':'blob','content':content})
    manifest={'repository':'jhwi0424/stm32f103-beijing-clock-0.91oled','text':text,'binary':binary}
    out=ROOT/'build/github-upload.json';out.write_text(json.dumps(manifest,ensure_ascii=False),encoding='utf-8')
    stats={'text_files':len(text),'binary_files':len(binary),'text_bytes':sum(len(e['content'].encode()) for e in text),'manifest_bytes':out.stat().st_size}
    print(json.dumps(stats))
if __name__=='__main__':main()
