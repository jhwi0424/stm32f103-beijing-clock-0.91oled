"""Estimate this board's LSE drift against the PC, then set STM32F1 CAL.

Uses live RTC reads without stopping the MCU. See ST application note AN2604.
"""
import argparse,json,statistics,time
from stlink_clock import server,ROOT

def slope(samples):
    t0=samples[0]['host_midpoint'];x=[s['host_midpoint']-t0 for s in samples]
    y=[s['offset_ms'] for s in samples];mx=statistics.mean(x);my=statistics.mean(y)
    return sum((a-mx)*(b-my) for a,b in zip(x,y))/sum((a-mx)**2 for a in x)*1000

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--seconds',type=int,default=120);a=p.parse_args()
    if a.seconds<60:raise SystemExit('Measure at least 60 seconds')
    with server() as link:
        if link.read()['source']!=1:raise RuntimeError('Calibration requires LSE')
        old=int(link.command('read_memory 0x40006c2c 32 1'),0)&127
        uid=[int(x,0) for x in link.command('read_memory 0x1ffff7e8 32 3').split()]
        samples=[];start=time.monotonic();wall=time.time()
        for i in range(a.seconds+1):
            samples.append(link.sample())
            if i%15==0:print(f'{i}s: offset {samples[-1]["offset_ms"]:.3f} ms',flush=True)
            if i<a.seconds:time.sleep(max(0,start+i+1-time.monotonic()))
        if abs((time.time()-wall)-(time.monotonic()-start))>.01:raise RuntimeError('PC system time stepped during measurement; retry')
        ppm=slope(samples);new=round(old+ppm/(1e6/2**20))
        if not 0<=new<=127:raise RuntimeError(f'Required CAL {new} is outside hardware range; measured {ppm:.2f} ppm')
        report={'before_cal':old,'after_cal':new,'measured_ppm':ppm,'uid':uid,'samples':samples,'reference':'PC system clock, ST-Link RTC reads; temperature-dependent estimate'}
        (ROOT/'build/calibration.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        header='/* Board-specific estimate against PC clock. See build/calibration.json. */\n'
        header+=f'#define CLOCK_LSE_CALIBRATION {new}u\n'
        for i,v in enumerate(uid):header+=f'#define CLOCK_CAL_UID{i} 0x{v:08x}u\n'
        (ROOT/'firmware/calibration.h').write_text(header,encoding='ascii')
        link.command(f'write_memory 0x40006c2c 32 {{{new}}}')
        print(f'CAL {old} -> {new}; measured {ppm:.2f} ppm. Rebuild firmware to preserve this board-specific setting.',flush=True)
