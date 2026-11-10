"""Capture the firmware framebuffer through SWD for layout inspection.

This is the MCU's framebuffer, not a photograph of the physical panel.
"""
import json
from PIL import Image
from stlink_clock import server,ROOT
if __name__=='__main__':
    addr=json.loads((ROOT/'build/symbols.json').read_text())['framebuffer']
    with server() as link:
        frame=[int(x,0) for x in link.command(f'read_memory {addr} 8 512').split()]
        assert len(frame)==512
    img=Image.new('RGB',(128,32),(0,0,0))
    for y in range(32):
        for x in range(128):
            if frame[x+128*(y//8)]&(1<<(y%8)):img.putpixel((x,y),(220,245,255))
    img.resize((768,192),Image.Resampling.NEAREST).save(ROOT/'build/display-preview.png')
