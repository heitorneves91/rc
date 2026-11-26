"""Slice the final kit with a bounded process and deterministic safe plate layout.
Uses installed official BBL profiles; does not connect to or start a printer.
Run with the system Python, not within an interactive FreeCAD process.
"""
from pathlib import Path
import os,json,subprocess,resource,argparse,re,math,hashlib
os.sched_setaffinity(0,set(sorted(os.sched_getaffinity(0))[:2]));os.nice(10)
resource.setrlimit(resource.RLIMIT_AS,(4*1024**3,4*1024**3))
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source',type=Path,default=Path(__file__).resolve().parent,help='Alternative self-contained STL/manifest/process directory for matched comparisons')
parser.add_argument('--include-printed',action='store_true',help='Also queue the locked, already printed wing and bumper')
args=parser.parse_args()
base=args.source.resolve()
profiles=Path.home()/'.config/BambuStudio/system/BBL'
import tempfile
work=Path(tempfile.mkdtemp(prefix='rc-fairing-slice-'));print('Slicer work directory:',work,flush=True)
indexes={}
for kind in ['machine','process','filament']:
 indexes[kind]={}
 for path in (profiles/kind).glob('*.json'):
  d=json.loads(path.read_text());indexes[kind][d.get('name',path.stem)]=d

def resolve(kind,name):
 d=indexes[kind][name];out={}
 if d.get('inherits'):out.update(resolve(kind,d['inherits']))
 out.update(d);out.pop('inherits',None);return out

machine=resolve('machine','Bambu Lab P1S 0.4 nozzle')
process=resolve('process','0.20mm Standard @BBL P1P')
process.update(json.loads((base/'P1S_PLA_process.json').read_text()));process.pop('inherits',None)
filament=resolve('filament','Generic PLA');filament['filament_colour']=['#FFFFFF']
for n,v in [('machine',machine),('process',process),('filament',filament)]:
 (work/(n+'.json')).write_text(json.dumps(v,indent=2))
all_parts=json.loads((base/'print_manifest.json').read_text())
reused=[i['name'] for i in all_parts if i.get('already_printed',i['name'] in ('Rear_wing','Front_bumper'))]
manifest=[i for i in all_parts if args.include_printed or i['name'] not in reused]
revision=json.loads((base/'parameters.json').read_text())['revision'] if (base/'parameters.json').exists() else 3
# Rectangle packing intentionally prohibits nesting another model inside a
# shell's concave footprint, where tree supports/brims will be generated.
padding=10.0
width,height=256.0,228.0
bins=[]
def contains(a,b):
    return b[0]>=a[0]-1e-7 and b[1]>=a[1]-1e-7 and b[0]+b[2]<=a[0]+a[2]+1e-7 and b[1]+b[3]<=a[1]+a[3]+1e-7
def overlap(a,b):
    return min(a[0]+a[2],b[0]+b[2])>max(a[0],b[0])+1e-7 and min(a[1]+a[3],b[1]+b[3])>max(a[1],b[1])+1e-7
for item in sorted(manifest,key=lambda i:i['print_size_mm'][0]*i['print_size_mm'][1],reverse=True):
    w,h=[v+2*padding for v in item['print_size_mm'][:2]]
    selected=None
    for bi,plate in enumerate(bins):
        choices=[]
        for free in plate['free']:
            if w<=free[2]+1e-6 and h<=free[3]+1e-6:
                choices.append(((min(free[2]-w,free[3]-h),max(free[2]-w,free[3]-h),free[1],free[0]),free))
        if choices:selected=(bi,min(choices)[1]);break
    if selected is None:
        assert w<=width+1e-6 and h<=height+1e-6,(item['name'],w,h)
        bins.append({'free':[(0.,0.,width,height)],'placed':[]})
        selected=(len(bins)-1,bins[-1]['free'][0])
    bi,free=selected;x,y=free[:2];rect=(x,y,w,h)
    plate=bins[bi]
    assert not any(overlap(rect,p['rect']) for p in plate['placed'])
    new=[]
    for f in plate['free']:
        if not overlap(f,rect):new.append(f);continue
        fx,fy,fw,fh=f
        if x>fx+1e-7:new.append((fx,fy,x-fx,fh))
        if x+w<fx+fw-1e-7:new.append((x+w,fy,fx+fw-x-w,fh))
        if y>fy+1e-7:new.append((fx,fy,fw,y-fy))
        if y+h<fy+fh-1e-7:new.append((fx,y+h,fw,fy+fh-y-h))
    unique=list(dict.fromkeys(new))
    plate['free']=[f for i,f in enumerate(unique) if not any(j!=i and contains(g,f) for j,g in enumerate(unique))]
    plate['placed'].append(dict(name=item['name'],rect=rect))
layout={'plates':[]}
for bi,plate in enumerate(bins):
    objects=[]
    for placement in plate['placed']:
        x,y,_,_=placement['rect']
        # The source meshes have XY minimum (10,10); these are translations.
        objects.append(dict(path='print/'+placement['name']+'.stl',count=1,filaments=[1],assemble_index=[0],pos_x=[x],pos_y=[28+y],pos_z=[0]))
    layout['plates'].append(dict(plate_index=bi+1,plate_name='Fairing '+str(bi+1),need_arrange=False,objects=objects,plate_params={'print_sequence':'by layer'}))
(base/'plate_layout.json').write_text(json.dumps(layout,indent=2)+'\n')
runtime=json.loads(json.dumps(layout))
for plate in runtime['plates']:
    for obj in plate['objects']:obj['path']=str((base/obj['path']).resolve())
(work/'assemble.json').write_text(json.dumps(runtime,indent=2))
print('Manual plates:',len(bins),'with 20 mm model-box separation',flush=True)
cmd=[str(Path.home()/'tools/bambustudio'),'--debug','2','--load-settings',str(work/'machine.json')+';'+str(work/'process.json'),'--load-filaments',str(work/'filament.json'),'--arrange','0','--orient','0']
with (work/'run.log').open('w') as log:
 result=subprocess.run(cmd+['--load-assemble-list',str(work/'assemble.json'),'--slice','0','--export-3mf','sliced.3mf','--outputdir',str(work)],cwd=work,stdout=log,stderr=subprocess.STDOUT)
if result.returncode:raise RuntimeError('Slicer failed; see '+str(work/'run.log'))
r=json.loads((work/'result.json').read_text());assert r['return_code']==0
objects=[o for p in r['sliced_plates'] for o in p['objects']]
assert {o['name'].removesuffix('_1') for o in objects}=={it['name'] for it in manifest}, [o['name'] for o in objects]
assert r['wall_loops']==2 and abs(r['sparse_infill_density']-5)<1e-6
# Bambu's main_used_g includes model plus brim; total-minus-main is support.
# Measure brim extrusion separately to avoid labeling it as model material.
def brim_mass(path):
    feature='Custom';relative=False;last_e=0.;length=0.
    for line in path.open():
        if line.startswith('; FEATURE:'):
            feature=line.split(':',1)[1].strip();continue
        code=line.split(';',1)[0].strip()
        if code=='M83':relative=True
        elif code=='M82':relative=False
        elif code.startswith('G92 '):
            m=re.search(r'\bE(-?[\d.]+)',code)
            if m:last_e=float(m[1])
        elif code.startswith(('G0 ','G1 ','G2 ','G3 ')):
            m=re.search(r'\bE(-?[\d.]+)',code)
            if not m:continue
            e=float(m[1]);delta=e if relative else e-last_e;last_e=e
            if feature=='Brim' and delta>0 and re.search(r'\b[XY]',code):length+=delta
    return length*math.pi*(1.75/2)**2/1000*1.24
main_g=sum(f['main_used_g'] for p in r['sliced_plates'] for f in p['filaments'])
total_g=sum(f['total_used_g'] for p in r['sliced_plates'] for f in p['filaments'])
brim_g=sum(brim_mass(p) for p in work.glob('plate_*.gcode'))
assert not any(p.get('warning_message') for p in r['sliced_plates']), 'Inspect slicer plate warnings'
report=dict(status='PASS',revision=revision,software='Bambu Studio 02.08.02.61',
    printer='Bambu Lab P1S 0.4 nozzle',filament='Generic PLA, white',layer_height_mm=.2,
    walls=2,infill_percent=5,supports='Automatic tree, build plate only, threshold 35 degrees; critical-only OFF; small-overhang removal OFF',
    support_critical_regions_only=False,support_top_interface_layers=3,support_interface_spacing_mm=.35,
    brim_mm=6,auto_3d_orientation=False,parts=len(manifest),complete_assembly_parts=len(all_parts),
    reused_already_printed_parts=[] if args.include_printed else reused,
    plates=len(r['sliced_plates']),
    estimated_total_hours=round(sum(p['total_predication'] for p in r['sliced_plates'])/3600,3),
    estimated_model_g=round(main_g-brim_g,3),estimated_brim_g=round(brim_g,3),
    estimated_model_and_brim_g=round(main_g,3),estimated_support_g=round(total_g-main_g,3),
    estimated_total_g=round(total_g,3),
    mass_accounting='Bambu main_used_g includes brim; support=total_used_g-main_used_g. Brim estimated from feature-tagged extrusion at 1.75 mm / PLA 1.24 g/cm3.',
    resolved_profile_sha256={name:hashlib.sha256((work/(name+'.json')).read_bytes()).hexdigest() for name in ('machine','process','filament')},
    sliced_mesh_sha256={i['name']:hashlib.sha256((base/'print'/(i['name']+'.stl')).read_bytes()).hexdigest() for i in manifest},
    cli_return_code=0,layout='Deterministic bounding rectangles, 20 mm model-box separation; no nesting',
    plate_details=r['sliced_plates'],
    notes=['All queued parts sliced with conflict checks enabled; no G-code distributed.',
           'Successfully printed Rear_wing and Front_bumper are unchanged and omitted from the default queue.',
           'Current assembly is the highest suspension position; travel reserve is downward, with 3 mm residual upward tolerance.',
           'Two CPU cores, lower priority and a 4 GiB process limit. Slicer PASS is not physical print validation.'])
from support_material import per_part
report['estimated_support_by_part_g']=per_part(work)
(base/'slicer_report.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k not in ['plate_details']},indent=2),flush=True)
with (work/'project.log').open('w') as log:
 result=subprocess.run(cmd+['--load-assemble-list',str(work/'assemble.json'),'--export-3mf','fairing-P1S.3mf','--outputdir',str(base)],cwd=work,stdout=log,stderr=subprocess.STDOUT)
if result.returncode:raise RuntimeError('Model project export failed')
print('Model-only P1S project exported.',flush=True)
