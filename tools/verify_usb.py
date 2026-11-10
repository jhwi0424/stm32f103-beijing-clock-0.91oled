"""Verify the actual clock's USB protocol and continued independent running."""
import argparse,json,time
import serial
from serial.tools import list_ports
from usb_time_sync import read_reply,ROOT,VID,PID
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--seconds',type=int,default=20);a=p.parse_args()
    ports=[d.device for d in list_ports.comports() if d.device and d.vid==VID and d.pid==PID]
    if len(ports)!=1:raise RuntimeError(f'Expected one USB clock: {ports}')
    samples=[]
    with serial.Serial(ports[0],115200,timeout=1,write_timeout=1) as port:
        port.reset_input_buffer()
        for i in range(a.seconds+1):
            t0=time.time();port.write(b'INFO\n');port.flush();s,m,source,count=read_reply(port);t1=time.time()
            d={'host_before':t0,'host_after':t1,'utc':s,'ms':m,'source':source,'sync_count':count,'rtt_ms':(t1-t0)*1000,'offset_ms':(s+m/1000-(t0+t1)/2)*1000}
            samples.append(d)
            if i%10==0 or i==a.seconds:print(json.dumps(d),flush=True)
            assert source==1 and count>0
            assert abs(d['offset_ms'])<250
            if i<a.seconds:time.sleep(1)
    assert len({d['sync_count'] for d in samples})==1,'Unexpected repeated synchronization'
    assert samples[-1]['utc']>samples[0]['utc']
    (ROOT/'build/usb-verification.json').write_text(json.dumps({'port':ports[0],'samples':samples,'result':'PASS'},indent=2),encoding='utf-8')
    print('PASS: native USB identified, time correct, RTC advances, sync count unchanged',flush=True)
