"""Package only the remaining prints after CAD, slicing and preview validation.
Run with system Python after build/verify/render/slice and compare_support.py.
"""
from pathlib import Path
import hashlib
import json
import zipfile
import xml.etree.ElementTree as ET

BASE=Path(__file__).resolve().parent
CAD=BASE.parent

def main():
    manifest=json.loads((BASE/'print_manifest.json').read_text())
    verification=json.loads((BASE/'verification.json').read_text())
    sliced=json.loads((BASE/'slicer_report.json').read_text())
    comparison=json.loads((BASE/'support_comparison.json').read_text())
    assert verification['status']==sliced['status']==comparison['status']=='PASS'
    assert verification['revision']==sliced['revision']==3
    remaining=[i for i in manifest if not i['already_printed']]
    reused=[i['name'] for i in manifest if i['already_printed']]
    assert set(reused)=={'Rear_wing','Front_bumper'}
    assert sliced['parts']==len(remaining)
    assert verification['printable_parts']==len(manifest)
    assert verification['mechanical_parts']==74
    for name,locked in json.loads((BASE/'printed_reference/locked_parts.json').read_text()).items():
        assert hashlib.sha256((BASE/'print'/(name+'.stl')).read_bytes()).hexdigest()==locked['stl_sha256']
    with zipfile.ZipFile(BASE/'fairing-P1S.3mf') as archive:
        assert not any(n.endswith('.gcode') for n in archive.namelist())
        settings=json.loads(archive.read('Metadata/project_settings.config'))
        assert str(settings['wall_loops'])=='2'
        assert settings['sparse_infill_density']=='5%'
        assert str(settings['support_critical_regions_only'])=='0'
        objects=ET.fromstring(archive.read('Metadata/model_settings.config'))
        names={o.find("metadata[@key='name']").get('value').removesuffix('_1') for o in objects.findall('object')}
        assert names=={i['name'] for i in remaining},names
    (BASE/'START-HERE.txt').write_text(f'''RC FAIRING REVISION 3 — LOWER SUPPORT / P1S / WHITE PLA

Open fairing/fairing-P1S.3mf in Bambu Studio. The queue has {len(remaining)} parts
on {sliced['plates']} plates. The complete CAD contains {len(manifest)} components.
REUSE your successfully printed Rear_wing_1 and Front_bumper_1: they are unchanged
and omitted from this print queue. Their endplates/pylons remain to be printed.

Use the supplied orientations and arrangement. Select your actual PLA profile
and re-slice before printing. Two walls, 5% infill, fixed 0.20 mm layers, Arachne,
6 mm brim, automatic trees. Critical-only supports are OFF. Do not disable all
supports. Inspect the fender curves, interfaces, tabs and window corners in
Preview. Toolpath conflict checks remain enabled. No G-code is supplied.

Large wraparound shells are replaced with separate hood/deck panels, short
fenders, cabin sills and window frames. Tapered recessed glue laps align most
joints. Each nose has FOUR main panels plus ONE small cheek backing strip.
Dry-fit first. Read FAIRING.txt and use the exploded CAD preview for assembly.
The original complete Nose_L/R, Cab_L/R and Tail_L/R STLs are obsolete.

Queued slicer estimates: {sliced['estimated_model_g']:.1f} g model,
{sliced['estimated_brim_g']:.1f} g brim, {sliced['estimated_support_g']:.1f} g support;
{sliced['estimated_total_g']:.1f} g total, {sliced['estimated_total_hours']:.2f} hours.
Matched old/new support comparison: {comparison['support_reduction_percent']:.1f}% less support.
These are predictions, not measurements of a successful physical print.
Start with the revised right-nose components before committing the full kit.

The preview nose-print-orientations.png is an explanatory layout of the parts,
not the actual plate arrangement or a picture of generated supports.
Native editable fairing.FCStd and integrated full_assembly.FCStd are supplied
separately. Use those for fit checks; do not print the full assembly as one item.
''')
    names=['fairing-P1S.3mf','START-HERE.txt','FAIRING.txt','P1S_PLA_process.json',
           'parameters.json','print_manifest.json','verification.json','slicer_report.json',
           'support_comparison.json','support-baseline-revision2.json','plate_layout.json','replacement_map.json']
    files=[BASE/'print'/(i['name']+'.stl') for i in remaining]+[BASE/n for n in names]
    files += [CAD/'fairing-preview'/n for n in ['front-isometric.png','rear.png','exploded.png','nose-print-orientations.png']]
    checksums=''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(CAD).as_posix()+'\n' for p in files)
    (BASE/'SHA256SUMS.txt').write_text(checksums)
    files.append(BASE/'SHA256SUMS.txt')
    with zipfile.ZipFile(CAD/'fairing-print.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for path in files:archive.write(path,path.relative_to(CAD))
    with zipfile.ZipFile(CAD/'fairing-print.zip') as archive:
        assert archive.testzip() is None
        assert sum(n.endswith('.stl') for n in archive.namelist())==len(remaining)
        assert not any(n.endswith('/Rear_wing.stl') or n.endswith('/Front_bumper.stl') for n in archive.namelist())
    print(f'PASS: {len(remaining)} remaining STL files, {sliced["plates"]} plates; printed wing/bumper excluded')

if __name__=='__main__':main()
