"""Build using STM32CubeIDE's GCC, without requiring Keil or online packages."""
from pathlib import Path
import subprocess, json, shutil
ROOT=Path(__file__).resolve().parents[1]
def find_tool(name):
    on_path=shutil.which(name)
    if on_path:return Path(on_path)
    matches=list(Path('C:/ST').glob(f'**/{name}.exe'))
    if not matches:raise RuntimeError(f'{name} not found; install STM32CubeIDE or add it to PATH')
    return matches[0]
if __name__=='__main__':
    gcc=find_tool('arm-none-eabi-gcc'); bindir=gcc.parent
    out=ROOT/'build';out.mkdir(exist_ok=True)
    lib=ROOT/'vendor/libopencm3-clock'
    args=[str(gcc),'-mcpu=cortex-m3','-mthumb','-mfloat-abi=soft','-DSTM32F1','-std=c11','-Os','-g3','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-ffunction-sections','-fdata-sections',f'-I{lib / "include"}',str(ROOT/'firmware/main.c'),f'-L{lib / "lib"}',f'-T{ROOT / "firmware/clock.ld"}','-Wl,--gc-sections',f'-Wl,-Map={out / "clock.map"}','--specs=nano.specs','--specs=nosys.specs','-lopencm3_stm32f1','-lc','-lgcc','-lnosys','-o',str(out/'clock.elf')]
    args.insert(1,'-nostartfiles')
    subprocess.run(args,check=True)
    for fmt,ext in [('binary','bin'),('ihex','hex')]:subprocess.run([str(bindir/'arm-none-eabi-objcopy.exe'),'-O',fmt,str(out/'clock.elf'),str(out/f'clock.{ext}')],check=True)
    symbols=subprocess.check_output([str(bindir/'arm-none-eabi-nm.exe'),str(out/'clock.elf')],text=True)
    address=next(int(l.split()[0],16) for l in symbols.splitlines() if l.endswith(' clock_status'))
    frame=next(int(l.split()[0],16) for l in symbols.splitlines() if l.endswith(' framebuffer'))
    (out/'symbols.json').write_text(json.dumps({'clock_status':address,'framebuffer':frame},indent=2))
    subprocess.run([str(bindir/'arm-none-eabi-size.exe'),str(out/'clock.elf')],check=True)
