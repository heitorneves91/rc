"""Attribute support extrusion to each model in a completed Bambu CLI slice.
The sum must match the slicer's official support total within 0.1 g. This uses
feature tags and object-label ordering, with a single-object plate fallback.
"""
import json,sys,re,math
from pathlib import Path

def per_part(work):
 result=json.loads((work/'result.json').read_text());out={}
 for plate in result['sliced_plates']:
  if len(plate['objects'])==1:
   out[plate['objects'][0]['name'].removesuffix('_1')]=sum(f['total_used_g']-f['main_used_g'] for f in plate['filaments']);continue
  path=work/('plate_'+str(plate['id'])+'.gcode');feature='';relative=False;last=0;active=None;ids=[];length={}
  for line in path.open():
   if line.startswith('; model label id:'):ids=[int(x) for x in line.split(':',1)[1].split(',')]
   if line.startswith('; start printing object'):active=int(line.split(':')[-1]);continue
   if line.startswith('; stop printing object'):active=None;continue
   if line.startswith('; FEATURE:'):feature=line.split(':',1)[1].strip();continue
   code=line.split(';',1)[0].strip()
   if code=='M83':relative=True
   elif code=='M82':relative=False
   elif code.startswith('G92 '):
    m=re.search(r'\bE(-?[\d.]+)',code)
    if m:last=float(m[1])
   elif code.startswith(('G0 ','G1 ','G2 ','G3 ')):
    m=re.search(r'\bE(-?[\d.]+)',code)
    if not m:continue
    e=float(m[1]);delta=e if relative else e-last;last=e
    if active is not None and feature in ['Support','Support interface'] and delta>0 and re.search(r'\b[XY]',code):length[active]=length.get(active,0)+delta
  assert len(ids)==len(plate['objects'])
  for uid,obj in zip(ids,plate['objects']):out[obj['name'].removesuffix('_1')]=round(length.get(uid,0)*math.pi*(1.75/2)**2/1000*1.24,4)
 official=sum(f['total_used_g']-f['main_used_g'] for p in result['sliced_plates'] for f in p['filaments'])
 assert abs(sum(out.values())-official)<.1,(sum(out.values()),official)
 return out
if __name__=='__main__':
 for directory in sys.argv[1:]:
  d=Path(directory);out=per_part(d);(d/'per-part-support.json').write_text(json.dumps(out,indent=2))
  print(directory,'total',round(sum(out.values()),2));print(json.dumps(dict(sorted(out.items(),key=lambda x:-x[1])[:12]),indent=2))
