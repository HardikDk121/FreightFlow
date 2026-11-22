# Rebuilds the three icon images from the original logo (run from app/: python3 assets/icon/make_icons.py).
# Cuts the artwork out of the black square, drops the white page around it and the JPEG noise in the
# black, and writes the full-bleed icon, the adaptive foreground and the monochrome icon.
from PIL import Image, ImageDraw
import numpy as np
src=np.array(Image.open('assets/icon/source_logo.jpeg').convert('RGB')).astype(float)
BG=np.array([11,11,15],float)
crop=src[293:959,183:1020]
d=(crop-BG).max(axis=2)
# Below 20 is JPEG noise in the black; ramp to full over the next 120 levels to keep edges smooth.
alpha=np.clip((d-20)/120,0,1)
colour=np.where(alpha[...,None]>0.02, BG+(crop-BG)/np.maximum(alpha[...,None],0.02), 0)
art=Image.fromarray(np.dstack([np.clip(colour,0,255),alpha*255]).astype(np.uint8),'RGBA')
bbox=art.getchannel('A').point(lambda v:255 if v>8 else 0).getbbox(); art=art.crop(bbox)

def place(size, fraction, background):
    canvas=Image.new('RGBA',(size,size),background)
    w,h=art.size; s=size*fraction/max(w,h)
    piece=art.resize((round(w*s),round(h*s)),Image.LANCZOS)
    canvas.alpha_composite(piece,((size-piece.width)//2,(size-piece.height)//2))
    return canvas

out='assets/icon/'
place(1024,0.74,(11,11,15,255)).convert('RGB').save(out+'app_icon.png')
place(1024,0.60,(0,0,0,0)).save(out+'app_icon_foreground.png')
mono=np.array(place(1024,0.60,(0,0,0,0))); mono[...,:3]=255; Image.fromarray(mono).save(out+'app_icon_monochrome.png')

prev=Image.new('RGB',(3*300+40,320),(230,230,235))
full=Image.open(out+'app_icon.png').resize((260,260),Image.LANCZOS)
fg=Image.open(out+'app_icon_foreground.png').resize((260,260),Image.LANCZOS)
for i,shape in enumerate(['round','squircle','ios']):
    m=Image.new('L',(260,260),0); dr=ImageDraw.Draw(m)
    if shape=='round': dr.ellipse((0,0,259,259),fill=255)
    else: dr.rounded_rectangle((0,0,259,259),radius=70 if shape=='squircle' else 58,fill=255)
    if shape=='ios': tile=full
    else:
        tile=Image.new('RGBA',(260,260),(11,11,15,255)); tile.alpha_composite(fg); tile=tile.convert('RGB')
    prev.paste(tile,(20+i*300,30),m)
prev.save('assets/icon/preview.png')
