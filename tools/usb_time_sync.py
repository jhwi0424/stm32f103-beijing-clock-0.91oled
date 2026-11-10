"""Watch this project's USB CDC clock; sync once on each insertion.

Requirements: Python 3 + pyserial. Works on Windows 10/11 with built-in usbser.
No internet access: the source is the computer's system UTC clock.
"""
import argparse, ctypes, datetime, logging, os, struct, time
from pathlib import Path
import serial
from serial.tools import list_ports

ROOT=Path(__file__).resolve().parents[1]
LOG=ROOT/'build/usb-time-sync.log'
VID,PID=0x1209,0xb103

def read_reply(port):
    line=port.readline().decode('ascii',errors='replace').strip().split()
    if len(line)!=5 or line[0]!='BJT1':raise RuntimeError(f'Unexpected clock reply: {line!r}')
    return list(map(int,line[1:]))

def sync(port_name):
    with serial.Serial(port_name,115200,timeout=1,write_timeout=1) as port:
        port.reset_input_buffer();port.write(b'INFO\n');port.flush()
        read_reply(port) # Verify the device before sending a timestamp.
        ns=time.time_ns();seconds=ns//1_000_000_000;ms=ns//1_000_000%1000
        port.write(b'BJT1'+struct.pack('<III',seconds,ms,seconds^ms^0x314a5442));port.flush()
        actual,actual_ms,source,count=read_reply(port)
        if abs((actual+actual_ms/1000)-time.time())>1:raise RuntimeError('Time acknowledgment is outside the allowed window')
        logging.info('%s synchronized: %s; RTC source=%s; count=%s',port_name,
            datetime.datetime.fromtimestamp(actual,datetime.timezone(datetime.timedelta(hours=8))).isoformat(),source,count)

def watch(once=False,resync_seconds=0):
    # Prevent two watchers from fighting over the serial port.
    mutex=None
    if os.name=='nt':
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateMutexW.argtypes=[ctypes.c_void_p,ctypes.c_bool,ctypes.c_wchar_p]
        kernel.CreateMutexW.restype=ctypes.c_void_p
        mutex=kernel.CreateMutexW(None,False,'Local\\STM32BeijingClockUSBWatcher')
        if not mutex:raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error()==183:return
    last={};warned={}
    try:
        while True:
            ports={p.device for p in list_ports.comports() if p.device and p.vid==VID and p.pid==PID}
            for missing in set(last)-ports:last.pop(missing,None)
            for name in ports:
                now=time.monotonic()
                if name in last and (not resync_seconds or now-last[name]<resync_seconds):continue
                try:sync(name);last[name]=now;warned.pop(name,None)
                except (OSError,serial.SerialException,RuntimeError) as exc:
                    if now-warned.get(name,-1e12)>30:
                        logging.warning('%s: %s; will retry',name,exc);warned[name]=now
            if once:return bool(ports and last)
            time.sleep(.25)
    finally:
        if mutex:
            kernel.CloseHandle.argtypes=[ctypes.c_void_p];kernel.CloseHandle(mutex)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--once',action='store_true');p.add_argument('--resync-seconds',type=int,default=0);a=p.parse_args()
    LOG.parent.mkdir(exist_ok=True)
    from logging.handlers import RotatingFileHandler
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s',
        handlers=[RotatingFileHandler(LOG,maxBytes=500000,backupCount=2,encoding='utf-8')])
    logging.info('USB clock watcher started')
    ok=watch(a.once,a.resync_seconds)
    if a.once:raise SystemExit(0 if ok else 2)
