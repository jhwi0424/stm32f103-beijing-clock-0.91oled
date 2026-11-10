"""Observe USB enumeration and watcher logs without opening the serial port."""
import argparse,datetime,json,time
from pathlib import Path
from serial.tools import list_ports
from usb_time_sync import ROOT,VID,PID

def now():return datetime.datetime.now().astimezone().isoformat(timespec='milliseconds')
def monitor(seconds):
    log=ROOT/'build/usb-time-sync.log'
    report=ROOT/'build/usb-plug-monitor.jsonl'
    offset=log.stat().st_size if log.exists() else 0
    previous=None;stop=time.monotonic()+seconds
    with report.open('a',encoding='utf-8',buffering=1) as out:
        def emit(kind,**data):
            line=json.dumps({'time':now(),'event':kind,**data},ensure_ascii=True)
            print(line,flush=True);out.write(line+'\n')
        emit('monitor_started',seconds=seconds)
        while time.monotonic()<stop:
            ports=sorted({p.device for p in list_ports.comports() if p.device and p.vid==VID and p.pid==PID})
            if ports!=previous:
                emit('usb_present' if ports else 'usb_absent',ports=ports)
                previous=ports
            if log.exists():
                size=log.stat().st_size
                if size<offset:offset=0
                with log.open('rb') as f:
                    f.seek(offset);data=f.read()
                # Do not consume a partially written log line.
                complete,sep,_=data.rpartition(b'\n')
                if sep:
                    for line in complete.decode('utf-8',errors='replace').splitlines():
                        emit('sync_success' if ' synchronized:' in line else 'watcher_log',message=line)
                    offset+=len(complete)+1
            time.sleep(.2)
        emit('monitor_window_finished')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--seconds',type=int,default=900);a=p.parse_args()
    monitor(a.seconds)
