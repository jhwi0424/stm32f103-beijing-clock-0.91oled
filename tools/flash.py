import subprocess,sys
from build import ROOT,find_tool
if __name__=='__main__':
    cli=find_tool('STM32_Programmer_CLI')
    subprocess.run([str(cli),'-c','port=SWD','freq=1000','-d',str(ROOT/'build/clock.hex'),'-v','-rst'],check=True)
    # Startup includes crystal detection on a cold board.
    import time
    time.sleep(6)
    subprocess.run([sys.executable,str(ROOT/'tools/stlink_clock.py'),'--sync'],check=True)
