"""Geometry and exported-print checks. Execute with FreeCAD's Python runtime.
Writes verification.json only after completing the checks; nonzero failures
must be resolved before describing the design as checked.
"""
import json
import math
import hashlib
from pathlib import Path
import FreeCAD as App
import Part
import Mesh

HERE=Path(__file__).resolve().parent
CAD=HERE.parent
V=App.Vector

def global_shape(obj):
    s=obj.Shape.copy()
    s.Placement=obj.getGlobalPlacement().multiply(obj.Placement.inverse()).multiply(s.Placement)
    return s

def overlap_boxes(a,b):
    return (min(a.XMax,b.XMax)>max(a.XMin,b.XMin)+1e-6 and
            min(a.YMax,b.YMax)>max(a.YMin,b.YMin)+1e-6 and
            min(a.ZMax,b.ZMax)>max(a.ZMin,b.ZMin)+1e-6)

def main(measure_distances=False):
    f=App.openDocument(str(CAD/'fairing.FCStd'))
    a=App.openDocument(str(CAD/'full_assembly.FCStd'))
    physical=list(f.getObject('Fairing').Group)
    mechanical=[o for o in a.Objects if o.TypeId=='Part::Feature' and 'SourceBody' in o.PropertiesList]
    assert len(mechanical)==74,len(mechanical)
    manifest=json.loads((HERE/'print_manifest.json').read_text())
    params=json.loads((HERE/'parameters.json').read_text())
    assert len(physical)==len(manifest)
    assert {p.stem for p in (HERE/'print').glob('*.stl')}=={r['name'] for r in manifest}, 'Stale/missing STL files'
    installed=a.getObject('Fairing')
    assert installed and len(installed.Group)==len(physical)
    for source in physical:
        copy=a.getObject('Fairing_'+source.Name)
        assert copy is not None and abs(copy.Shape.Volume-source.Shape.Volume)<.001

    errors=[];print_rows=[]
    locked=json.loads((HERE/'printed_reference/locked_parts.json').read_text())
    for name,reference in locked.items():
        mesh_path=HERE/'print'/(name+'.stl')
        assert hashlib.sha256(mesh_path.read_bytes()).hexdigest()==reference['stl_sha256'], 'Changed already printed mesh: '+name
        obj=f.getObject(name)
        assert abs(obj.Shape.Volume-reference['cad_volume_mm3'])<1e-7, 'Changed already printed volume: '+name
        original=Part.Shape();original.read(str(HERE/'printed_reference'/(name+'.brep')))
        assert obj.Shape.cut(original).Volume+original.cut(obj.Shape).Volume<1e-6, 'Changed already printed shape: '+name
        assert next(i for i in manifest if i['name']==name)['already_printed']

    for item in manifest:
        name=item['name'];o=f.getObject(name);s=o.Shape
        if not s.isValid() or len(s.Solids)!=1:errors.append('Invalid CAD solid '+name)
        mesh=Mesh.Mesh(str(HERE/'print'/(name+'.stl')))
        b=mesh.BoundBox
        dims=[b.XLength,b.YLength,b.ZLength]
        if not mesh.isSolid():errors.append('Non-watertight STL '+name)
        if min(b.XMin,b.YMin,b.ZMin)<-1e-3:errors.append('Below print plate '+name)
        if abs(b.ZMin)>1e-3:errors.append('Floating print '+name)
        if b.XMax>251 or b.YMax>251 or b.ZMax>246:errors.append('Outside conservative P1S envelope '+name)
        if max(abs(v-w) for v,w in zip(dims,item['print_size_mm']))>.03:errors.append('Print-size mismatch '+name)
        if abs(abs(mesh.Volume)-s.Volume)/s.Volume>.015:errors.append('Mesh volume mismatch '+name)
        # Verify the intended build direction, not just whether the rotated
        # bounding box fits. +90 X builds from aft to fore; -90 does the reverse.
        if name.startswith(('Nose_fender_aft','Tail_fender_aft','Nose_cheek','Nose_fender_fore','Tail_fender_fore')):
            rotation=App.Rotation(*item['print_transform']['rotation_quaternion'])
            direction=rotation.multVec(V(0,1,0)).z
            expected=-1 if 'fender_fore' in name else 1
            if direction*expected<.999:errors.append('Wrong end on bed: '+name)
        if name.startswith('Cab_sill'):
            ps=f.getObject('Print_'+name).Shape
            contact=ps.common(Part.makeBox(256,256,.2,V(0,0,0))).Volume/.2
            if contact<150:errors.append(f'Inadequate sill/pad bed contact {name}: {contact:.2f} mm^2')
            print('Cab sill first-layer area:',name,round(contact,1),'mm^2',flush=True)
        print_rows.append(dict(part=name,size_mm=[round(x,3) for x in dims],volume_cm3=round(s.Volume/1000,3),facets=mesh.CountFacets))
    print('Print envelopes checked:',len(print_rows),flush=True)
    x0,y0,z0,x1,y1,z1=params['steering_reserve']
    reserve=Part.makeBox(x1-x0,y1-y0,z1-z0,V(x0,y0,z0))
    reserves=[('steering_saver',reserve)]
    for y in (-32.5,-301):
        low=Part.makeCylinder(48.5,140,V(92,y,8),V(1,0,0))
        high=Part.makeCylinder(48.5,140,V(92,y,31),V(1,0,0))
        bridge=Part.makeBox(140,97,23,V(92,y-48.5,8))
        tool=low.fuse(high).fuse(bridge).removeSplitter()
        reserves.append((f'wheel_droop_{y}_R',tool))
        reserves.append((f'wheel_droop_{y}_L',tool.mirror(V(0,0,0),V(1,0,0))))
    # Check each overlapping steering capsule separately: never fuse or cut
    # the compound as one huge Boolean operation.
    for i,solid in enumerate(f.getObject('Front_steering_and_bump_reserve').Shape.Solids):
        reserves.append((f'front_steering_capsule_{i}',solid))
    # User supplied a 20 mm shaft extension; retain 10 mm extra axial margin.
    servo=a.getObject('Steering_servo')
    tip=servo.getGlobalPlacement().multVec(V(9.85,30.05,44.55))
    axis=servo.getGlobalPlacement().Rotation.multVec(V(0,0,1))
    end=tip+axis*30
    assert reserve.isInside(tip,1e-6,True) and reserve.isInside(end,1e-6,True)
    checks=[dict(servo_saver_added_shaft_mm=20,extra_axial_margin_mm=10,
                 shaft_tip_mm=list(tip),reserved_endpoint_mm=list(end),diameter='unknown')];shapes={o.Name:global_shape(o) for o in physical}
    bounds={n:s.optimalBoundingBox() for n,s in shapes.items()}
    for rn,rs in reserves:
        rb=rs.optimalBoundingBox()
        for n,s in shapes.items():
            if overlap_boxes(bounds[n],rb):
                vol=s.common(rs).Volume
                if vol>.05:errors.append(f'Clearance reserve collision {n} / {rn}: {vol:.3f} mm^3')
        checks.append(rn)
    print('Reserved clearances checked',flush=True)
    # Compare every body part against actual transformed mechanical solids.
    collisions=[]
    for m in mechanical:
        ms=global_shape(m);mb=ms.optimalBoundingBox()
        for n,s in shapes.items():
            if overlap_boxes(bounds[n],mb):
                vol=s.common(ms).Volume
                if vol>.05:collisions.append(dict(body=n,mechanical=m.Name,volume_mm3=round(vol,4)))
    print('Mechanical collision checks done:',len(collisions),'collisions',flush=True)
    # Separate printed components must not occupy the same material volume.
    body_collisions=[]
    names=list(shapes)
    for i,n in enumerate(names):
        for other in names[i+1:]:
            if overlap_boxes(bounds[n],bounds[other]):
                vol=shapes[n].common(shapes[other]).Volume
                if vol>.05:body_collisions.append(dict(a=n,b=other,volume_mm3=round(vol,4)))
    print('Printed-part collision checks done:',len(body_collisions),'collisions',flush=True)
    if collisions:errors.append('Mechanical intersections found')
    if body_collisions:errors.append('Printed-part intersections found')
    # Parent graph stays solver-free and acyclic; no external live links.
    for d in (f,a):
        seen=set();active=set()
        def visit(o):
            if o.Name in active:raise AssertionError('Cyclic object graph: '+o.Name)
            if o.Name in seen:return
            active.add(o.Name)
            for child in o.OutList:visit(child)
            active.remove(o.Name);seen.add(o.Name)
        for o in d.Objects:
            visit(o)
            if o.TypeId.startswith(('Assembly::','App::Link')):errors.append('Unexpected solver/live link '+o.Name)
    # Optional precise minimum-distance measurements can be slow on curved
    # trimmed NURBS. Core verification above checks every exact intersection
    # and the explicit saver/motion clearance volumes without that search.
    for n in ['Steering_servo','Steering_bellcrank_pair','Servo_to_bellcrank_link','Camera_and_ESP32_support']:
        item=dict(component=n,volumetric_intersection=False)
        if measure_distances:
            ms=global_shape(a.getObject(n))
            shell=[s for nn,s in shapes.items() if nn.startswith(('Cab_','Roof_cap','Nose_'))]
            item['minimum_body_clearance_mm']=round(min(ms.distToShape(s)[0] for s in shell),3)
        checks.append(item)
    assert params['wall']==1.0
    process=json.loads((HERE/'P1S_PLA_process.json').read_text())
    assert process['wall_loops']=='2' and process['sparse_infill_density']=='5%'
    assert process['support_critical_regions_only']=='0'
    assert not any(o.Name=='Tail_vent' for o in physical)
    assert f.getObject('Rear_light_L') and f.getObject('Rear_light_R')
    report=dict(revision=params['revision'],reused_printed_parts=locked,status='PASS' if not errors else 'FAIL',errors=errors,printable_parts=len(physical),mechanical_parts=74,shell_wall_mm=1.0,print_walls=2,infill_percent=5,
                print_volume_mm=[256,256,256],design_limit_mm=246,
                steering_reserve_mm=params['steering_reserve'],motion_assumptions='Current assembly is maximum compression. Continuous wheel movement -20 mm down to +3 mm residual upward tolerance; front steering +/-30 degrees in 5-degree steps about the knuckle, with 3 mm tire inflation. No +15 mm bump allowance. Not a solved articulated suspension trajectory.',
                clearances=checks,mechanical_collisions=collisions,printed_part_collisions=body_collisions,
                total_solid_volume_cm3=round(sum(s.Volume for s in shapes.values())/1000,2),
                estimated_PLA_mass_g_at_1_24=round(sum(s.Volume for s in shapes.values())/1000*1.24,1),parts=print_rows)
    (HERE/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('parts',)},indent=2),flush=True)
    if errors:raise RuntimeError('Fairing verification failed; see verification.json')
    return report

if __name__=='__main__':main()
