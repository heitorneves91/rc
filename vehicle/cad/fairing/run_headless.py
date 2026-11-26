"""Bounded build/verify/render launcher for a SEPARATE FreeCAD Python process.
Do not execute this inside an existing interactive FreeCAD Python console.
Example: <FreeCAD AppImage extraction>/AppRun python run_headless.py build
"""
import argparse
import os
from pathlib import Path
import sys

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('action',choices=['build','verify','render'])
args=parser.parse_args()

if hasattr(os,'sched_getaffinity'):
    allowed=sorted(os.sched_getaffinity(0))
    os.sched_setaffinity(0,set(allowed[:2]))
if hasattr(os,'setpriority') and os.getpriority(os.PRIO_PROCESS,0)<10:
    os.setpriority(os.PRIO_PROCESS,0,10)
try:
    import resource
    soft,hard=resource.getrlimit(resource.RLIMIT_AS)
    bound=4*1024**3
    if hard!=resource.RLIM_INFINITY:bound=min(bound,hard)
    resource.setrlimit(resource.RLIMIT_AS,(bound,bound))
except ImportError:
    pass
os.environ['OMP_NUM_THREADS']='2'
os.environ['OPENBLAS_NUM_THREADS']='1'
if os.environ.get('PATH_TO_FREECAD_LIBDIR'):
    sys.path.insert(0,os.environ['PATH_TO_FREECAD_LIBDIR'])

here=Path(__file__).resolve().parent
cad=here.parent
os.environ['RC_CAD_DIR']=str(cad)
target={'build':cad/'rebuild_fairing.FCMacro',
        'verify':cad/'verify_fairing.FCMacro',
        'render':here/'render_fairing.py'}[args.action]
exec(compile(target.read_text(),str(target),'exec'),{'__file__':str(target),'__name__':'__main__'})
