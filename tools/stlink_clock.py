"""Read/sync the running clock over ST-Link without stopping its CPU."""
import argparse, contextlib, datetime, json, socket, statistics, subprocess, time
from pathlib import Path
from build import ROOT, find_tool

FIELDS='magic version uptime_ms utc ms source synced oled_address oled_acks sync_count sequence set_sec set_ms checksum applied rtc_div faults'.split()
class Link:
    def __init__(self,port=16666):
        self.sock=socket.create_connection(('127.0.0.1',port),timeout=3)
        self.address=json.loads((ROOT/'build/symbols.json').read_text())['clock_status']
    def command(self,cmd):
        self.sock.sendall(cmd.encode()+b'\x1a');data=b''
        while not data.endswith(b'\x1a'):
            chunk=self.sock.recv(4096)
            if not chunk:raise ConnectionError('OpenOCD disconnected')
            data+=chunk
        result=data[:-1].decode()
        if result.startswith('Error'):raise RuntimeError(result)
        return result
    def read(self):
        values=[int(x,0) for x in self.command(f'read_memory {self.address} 32 {len(FIELDS)}').split()]
        if len(values)!=len(FIELDS) or values[0]!=0x424a5431:raise RuntimeError('Clock firmware signature not found')
        return dict(zip(FIELDS,values))
    def write(self,offset,values):
        return self.command(f'write_memory {self.address+offset} 32 '+'{'+ ' '.join(str(x) for x in values)+'}')
    def sync(self):
        old=self.read();seq=old['applied']+1
        # Write payload first and sequence last; target checks the complete transaction.
        ms=time.time_ns()//1_000_000;s,m=divmod(ms,1000)
        t0=time.perf_counter()
        self.write(44,[s,m,s^m^seq^0x314a5442])
        self.write(40,[seq])
        for _ in range(100):
            status=self.read()
            if status['applied']==seq:break
            time.sleep(.01)
        else:raise RuntimeError('Clock did not acknowledge time')
        if time.perf_counter()-t0>.25:raise RuntimeError('ST-Link transfer too slow; retry time synchronization')
        return status
    def sample(self):
        d=self.read()
        # Read the RTC itself, so OLED refresh cannot age the measurement.
        cmd='set a [read_memory 0x40002818 32 2]; set v [read_memory 0x40002810 32 2]; set b [read_memory 0x40002818 32 2]; set p [read_memory 0x40006c08 32 1]; list {*}$a {*}$v {*}$b {*}$p'
        for _ in range(10):
            t0=time.time();words=[int(x,0) for x in self.command(cmd).split()];t1=time.time()
            a=(words[0]<<16)|(words[1]&65535);b=(words[4]<<16)|(words[5]&65535)
            if a==b:break
        else:raise RuntimeError('RTC sample could not be read coherently')
        div=(words[2]<<16)|(words[3]&65535);phase=words[6]&65535
        if phase&32768:phase-=65536
        prescale=32767 if d['source']==1 else 62499
        device_ms=a*1000+(prescale-div)*1000//(prescale+1)+phase
        d['utc'],d['ms']=divmod(device_ms,1000)
        d['host_midpoint']=.5*(t0+t1);d['read_ms']=(t1-t0)*1000
        d['offset_ms']=(d['utc']+d['ms']/1000-d['host_midpoint'])*1000
        d['beijing']=datetime.datetime.fromtimestamp(d['utc'],datetime.timezone(datetime.timedelta(hours=8))).isoformat()
        return d
    def close(self):self.sock.close()

@contextlib.contextmanager
def server():
    ocd=find_tool('openocd')
    plugins=ocd.parents[3]
    scripts=next(plugins.glob('*.debug.openocd*/resources/openocd/st_scripts'))
    log=open(ROOT/'build/openocd.log','w',encoding='utf-8')
    args=[str(ocd),'-s',str(scripts),'-f','interface/stlink-dap.cfg','-f','target/stm32f1x.cfg','-c','bindto 127.0.0.1; tcl_port 16666; telnet_port disabled; gdb_port disabled; adapter speed 1000; init']
    process=subprocess.Popen(args,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
    link=None
    try:
        for _ in range(60):
            if process.poll() is not None:raise RuntimeError((ROOT/'build/openocd.log').read_text())
            try:link=Link();break
            except OSError:time.sleep(.1)
        if link is None:raise RuntimeError('OpenOCD startup timed out')
        yield link
    finally:
        if link:link.close()
        process.terminate()
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:process.kill();process.wait()
        log.close()

def main():
    p=argparse.ArgumentParser();p.add_argument('--sync',action='store_true');p.add_argument('--verify',type=int,default=0);p.add_argument('--existing-port',type=int);a=p.parse_args()
    manager=contextlib.closing(Link(a.existing_port)) if a.existing_port else server()
    with manager as link:
        if a.sync:link.sync()
        samples=[]
        for i in range(max(1,a.verify+1)):
            d=link.sample();samples.append(d)
            if i%10==0 or i==a.verify:print(json.dumps(d,ensure_ascii=False),flush=True)
            if i<a.verify:time.sleep(1)
        if a.verify:
            elapsed=samples[-1]['host_midpoint']-samples[0]['host_midpoint']
            x=[s['host_midpoint']-samples[0]['host_midpoint'] for s in samples]
            y=[s['offset_ms'] for s in samples];mx=statistics.mean(x);my=statistics.mean(y)
            ppm=sum((xx-mx)*(yy-my) for xx,yy in zip(x,y))/sum((xx-mx)**2 for xx in x)*1000
            report={'samples':samples,'elapsed_seconds':elapsed,'short_term_drift_ppm':ppm,'note':'Short measurement; not a long-term oscillator accuracy guarantee.'}
            (ROOT/'build/verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            assert all(d['synced'] and d['source']==1 and d['oled_address']==0x3c and d['faults']==0 for d in samples)
            assert samples[-1]['oled_acks']>samples[0]['oled_acks']
            assert abs(samples[-1]['offset_ms'])<250
            assert abs(samples[-1]['offset_ms']-samples[0]['offset_ms'])<30
            print(f'PASS: {elapsed:.1f}s running, offset {samples[-1]["offset_ms"]:.1f}ms, drift estimate {ppm:.1f}ppm')
if __name__=='__main__':main()
