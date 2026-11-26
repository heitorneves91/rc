"""Compare old/new remaining-kit support with identical resolved print profiles.
Use --rebuild-baseline after changing the process settings; that re-slices the
archived revision-2 geometry using the current conservative process preset.
"""
from pathlib import Path
import argparse
import json
import shutil
import subprocess
import sys
import tempfile

BASE=Path(__file__).resolve().parent

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rebuild-baseline',action='store_true')
    args=parser.parse_args()
    baseline_path=BASE/'support-baseline-revision2.json'
    if args.rebuild_baseline:
        archive=BASE/'history/revision2'
        work=Path(tempfile.mkdtemp(prefix='rc-r2-support-baseline-'))
        shutil.copytree(archive/'print',work/'print')
        shutil.copy2(archive/'print_manifest.json',work/'print_manifest.json')
        shutil.copy2(BASE/'P1S_PLA_process.json',work/'P1S_PLA_process.json')
        (work/'parameters.json').write_text(json.dumps({'revision':2}))
        subprocess.run([sys.executable,str(BASE/'slice_fairing.py'),'--source',str(work)],check=True)
        shutil.copy2(work/'slicer_report.json',baseline_path)
    old=json.loads(baseline_path.read_text())
    new=json.loads((BASE/'slicer_report.json').read_text())
    assert old['status']==new['status']=='PASS'
    assert old['resolved_profile_sha256']==new['resolved_profile_sha256'], 'Rebuild baseline with current process'
    assert set(old['reused_already_printed_parts'])==set(new['reused_already_printed_parts'])=={'Rear_wing','Front_bumper'}
    assert old['support_critical_regions_only']==new['support_critical_regions_only']==False
    assert new['estimated_support_g']<old['estimated_support_g'], 'Support reduction not achieved'
    keys=['parts','plates','estimated_model_g','estimated_brim_g','estimated_support_g','estimated_total_g','estimated_total_hours']
    report=dict(status='PASS',baseline_revision=2,current_revision=3,
        comparison='Remaining complete fairing kits; printed wing/bumper excluded from both. Same resolved printer, filament and conservative process; critical-only OFF, fixed 0.20 mm, 2 walls / 5% infill.',
        resolved_profile_sha256=new['resolved_profile_sha256'],
        baseline={k:old[k] for k in keys},current={k:new[k] for k in keys},
        support_saved_g=round(old['estimated_support_g']-new['estimated_support_g'],3),
        support_reduction_percent=round(100*(1-new['estimated_support_g']/old['estimated_support_g']),2),
        total_saved_g=round(old['estimated_total_g']-new['estimated_total_g'],3),
        total_reduction_percent=round(100*(1-new['estimated_total_g']/old['estimated_total_g']),2),
        notes=['Slicer estimates, not physical print validation.','The extra seams/parts and plate layouts are part of the manufacturing redesign.','Do not substitute the old critical-only totals for this matched baseline.'])
    if 'estimated_support_by_part_g' in old and 'estimated_support_by_part_g' in new:
        report['nose_support_comparison']={}
        for side in ('L','R'):
            previous=old['estimated_support_by_part_g']['Nose_'+side]
            current=sum(g for name,g in new['estimated_support_by_part_g'].items() if name.endswith('_'+side) and name.startswith(('Nose_','Join_Nose_')))
            report['nose_support_comparison'][side]=dict(baseline_support_g=round(previous,3),current_support_g=round(current,3),reduction_percent=round(100*(1-current/previous),2))
    (BASE/'support_comparison.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
