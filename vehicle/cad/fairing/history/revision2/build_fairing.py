"""Reproducible, solver-free fairing for the RC car. Run from rebuild_fairing.FCMacro.
All model coordinates are the full_assembly.FCStd global millimetre coordinates.
See FAIRING.txt, parameters.json and verification.json before changing geometry.
"""
from pathlib import Path
import json
import math
import FreeCAD as App
import Part
import MeshPart

HERE = Path(__file__).resolve().parent
CAD = HERE.parent
V = App.Vector
P = {
    'revision': 2,
    'servo_saver_added_shaft_mm': 20.0, 'servo_saver_extra_axial_margin_mm': 10.0,
    'wall': 1.0, 'seam_gap': 0.30, 'roof_split_z': 105.0,
    'seams_y': [-90.0, -246.0], 'wheel_arch_radius': 48.5,
    'wheel_arch_inner_x': 92.0, 'print_limit': 246.0,
    'wheel_travel_mm': [-20.0,3.0], 'wheel_clearance_mm': 3.0,
    'steering_reserve': [-65,-177,5,65,-78,50],
    'mount_x': 77.5, 'chassis_mount_x': 66.4,
    'mount_y': [-179.6,-232.4], 'screw_clearance': 3.4,
    'surface_corner_blend_mm': 7.0,
    'stations': [
        # Y, lower half-width, shoulder half-width, roof half-width,
        # skirt Z, shoulder Z, center/hood Z. Current wheels are full bump.
        [-350,100,119,62,5,78,74],
        [-327,105,128,70,5,84,79],
        [-301,108,132,75,5,87,80],
        [-277,104,126,73,4,85,80],
        [-256,94,111,69,3,74,83],
        [-232,87,94,60,3,68,97],
        [-211,84,91,55,3,67,116],
        [-183,84,90,55,3,67,118],
        [-155,84,92,56,3,69,116],
        [-126,87,98,65,4,75,98],
        [-98,92,106,70,5,83,83],
        [-66,103,125,75,7,87,82],
        [-32.5,110,132,77,9,89,82],
        [-5,104,122,73,9,84,78],
        [24,88,98,60,10,72,64],
        [45,60,67,42,11,56,48],
    ],
}

def box(x,y,z,dx,dy,dz):
    return Part.makeBox(dx,dy,dz,V(x,y,z))

def polygon(points):
    return Part.makePolygon([V(*p) for p in points]+[V(*points[0])])

def prism(points, vector):
    return Part.Face(polygon(points)).extrude(V(*vector))

def cylinder(r,h,start,axis=(0,0,1)):
    return Part.makeCylinder(r,h,V(*start),V(*axis))

def cut_many(shape, cutters):
    if not cutters:return shape
    tool=cutters[0] if len(cutters)==1 else cutters[0].multiFuse(cutters[1:]).removeSplitter()
    return shape.cut(tool).removeSplitter()

def section_poles(st, inset=0):
    y,wb,ww,wr,zb,zs,zt=st
    points=[(-wb,zb),(-ww+3,zs-9),(-ww,zs),(-wr-9,zt-2),(-wr,zt),
            (wr,zt),(wr+9,zt-2),(ww,zs),(ww-3,zs-9),(wb,zb)]
    if inset:
        # True miter offset of the X/Z profile. Simply reducing both widths
        # and heights can leave a sub-millimetre skirt on outward-sloping
        # panels. Extend the offset side lines below the skirt, leaving the
        # entire bottom open instead of retaining a closed floor.
        lines=[]
        for p,q in zip(points,points[1:]):
            dx,dz=q[0]-p[0],q[1]-p[1]
            length=math.hypot(dx,dz)
            lines.append(((p[0]+inset*dz/length,p[1]-inset*dx/length),(dx,dz)))
        def crossing(a,b):
            (px,pz),(dx,dz)=a;(qx,qz),(ex,ez)=b
            t=((qx-px)*ez-(qz-pz)*ex)/(dx*ez-dz*ex)
            return (px+t*dx,pz+t*dz)
        def bottom(line):
            (x,z),(dx,dz)=line
            target=zb-2.5*inset
            return (x+(target-z)*dx/dz,target)
        points=[bottom(lines[0])]+[crossing(a,b) for a,b in zip(lines,lines[1:])]+[bottom(lines[-1])]
    # Quadratic Bezier corner blends retain character lines while replacing
    # the box-like section vertices. Identical topology at every station
    # allows a single smooth cubic loft along the length of the body.
    blends=[]
    radius=max(.35,P['surface_corner_blend_mm']-inset)
    for i,p in enumerate(points):
        prev,nxt=points[i-1],points[(i+1)%len(points)]
        before=V(prev[0]-p[0],0,prev[1]-p[1]);after=V(nxt[0]-p[0],0,nxt[1]-p[1])
        trim=min(radius,.28*before.Length,.28*after.Length)
        center=V(p[0],y,p[1])
        start=center+before.normalize()*trim;end=center+after.normalize()*trim
        blends.append((start,center,end))
    edges=[]
    for i,(start,center,end) in enumerate(blends):
        nxt=blends[(i+1)%len(blends)][0]
        edges.extend([[start,center,end],[end,(end+nxt)*.5,nxt]])
    return edges


def section(st,inset=0):
    edges=[]
    for poles in section_poles(st,inset):
        c=Part.BezierCurve();c.setPoles(poles);edges.append(c.toShape())
    return Part.Wire(edges)


def monotone_slopes(x,y):
    # PCHIP/Hermite slopes: shape-preserving, without global loft ringing.
    h=[b-a for a,b in zip(x,x[1:])]
    d=[(b-a)/step for a,b,step in zip(y,y[1:],h)]
    m=[0.0]*len(y)
    for i in range(1,len(y)-1):
        if d[i-1]*d[i]>0:
            w1,w2=2*h[i]+h[i-1],h[i]+2*h[i-1]
            m[i]=(w1+w2)/(w1/d[i-1]+w2/d[i])
    def endpoint(h0,h1,d0,d1):
        value=((2*h0+h1)*d0-h0*d1)/(h0+h1)
        if value*d0<=0:return 0.0
        if d0*d1<0 and abs(value)>abs(3*d0):return 3*d0
        return value
    m[0]=endpoint(h[0],h[1],d[0],d[1])
    m[-1]=endpoint(h[-1],h[-2],d[-1],d[-2])
    return m


def loft(inset=0,cap=True):
    # Explicit tensor B-spline patches, quadratic across each profile edge and
    # shape-preserving cubic along Y. This fixes the parameter correspondence
    # of inner/outer skins and avoids the dips of an unconstrained global loft.
    stations=[list(x) for x in P['stations']]
    if inset and cap:
        stations[0][0]+=P['wall'];stations[-1][0]-=P['wall']
    ys=[s[0] for s in stations]
    profiles=[section_poles(st,inset) for st in stations]
    faces=[]
    for edge in range(len(profiles[0])):
        grid=[]
        for pole in range(3):
            values=[st[edge][pole] for st in profiles]
            mx=monotone_slopes(ys,[p.x for p in values]);mz=monotone_slopes(ys,[p.z for p in values])
            row=[values[0]]
            for i,h in enumerate(b-a for a,b in zip(ys,ys[1:])):
                row.extend([values[i]+V(mx[i],1,mz[i])*h/3,
                            values[i+1]-V(mx[i+1],1,mz[i+1])*h/3,values[i+1]])
            grid.append(row)
        surf=Part.BSplineSurface()
        surf.buildFromPolesMultsKnots(grid,[3,3],[4]+[3]*(len(ys)-2)+[4],[0.,1.],ys,False,False,2,3)
        faces.append(surf.toShape())
    faces.extend([Part.Face(section(stations[0],inset)),Part.Face(section(stations[-1],inset))])
    shell=Part.makeShell(faces);shell.sewShape()
    solid=Part.makeSolid(shell)
    if solid.Volume<0:solid.reverse()
    if not solid.isValid():solid.fix(1e-6,1e-7,1e-3)
    if not solid.isValid():raise RuntimeError('Invalid controlled surface skin '+str(inset))
    return solid


def mirrored(s):
    return s.mirror(V(0,0,0),V(1,0,0))

def roof_z(y):
    xs=[r[0] for r in P['stations']];zs=[r[6] for r in P['stations']]
    slopes=monotone_slopes(xs,zs)
    for i,(a,b) in enumerate(zip(xs,xs[1:])):
        if a<=y<=b:
            h=b-a;t=(y-a)/h
            return ((2*t**3-3*t*t+1)*zs[i]+(t**3-2*t*t+t)*h*slopes[i]
                    +(-2*t**3+3*t*t)*zs[i+1]+(t**3-t*t)*h*slopes[i+1])
    raise ValueError(y)


def hole_z(x,y,z0=-10,height=180):
    return cylinder(P['screw_clearance']/2,height,(x,y,z0))

def hex_prism(x,y,z,across_flat=5.8,depth=2.4):
    r=across_flat/math.sqrt(3)
    return prism([(x+r*math.cos(i*math.pi/3),y+r*math.sin(i*math.pi/3),z) for i in range(6)],(0,0,depth))

def clean(s, name):
    s=s.removeSplitter()
    if not s.isValid():s.fix(1e-6,1e-7,1e-3)
    if s.isNull() or not s.isValid() or len(s.Solids)!=1:
        for q in s.Solids:print('DISCONNECTED',name,q.Volume,q.optimalBoundingBox(),flush=True)
        raise RuntimeError(f'{name}: invalid/disconnected shape, {len(s.Solids)} solids')
    return s

PARTS=[]

def add(name, shape, orientation=(0,0,0), note='', support='Local support may be needed at cosmetic ledges'):
    shape=clean(shape,name)
    b=shape.optimalBoundingBox()
    PARTS.append(dict(name=name,shape=shape,orientation=orientation,note=note,support=support,
                      assembly_bounds_mm=[b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax]))
    print('PART',name,'volume',round(shape.Volume),flush=True)
    return shape


def front_motion_reserve():
    # Sweep the inflated tire about the actual knuckle axis, not its own
    # center: the wheel is offset 35 mm from the steering pivot.
    path=CAD/'full_assembly.FCStd'
    a=next((d for d in App.listDocuments().values() if d.FileName and Path(d.FileName).resolve()==path.resolve()),None)
    opened=a is None
    if opened:a=App.openDocument(str(path))
    center=a.getObject('Front_wheel_R').getGlobalPlacement().Base
    knuckle=a.getObject('Front_knuckle_R')
    local=V(15,-10.1,15)
    if knuckle.MirroredInstance:local.x=-local.x
    pivot=knuckle.getGlobalPlacement().multVec(local)
    P['front_wheel_center_mm']=list(center)
    P['front_steering_pivot_mm']=list(pivot)
    if opened:App.closeDocument(a.Name)
    # Keep each steering-angle capsule separate. Fusing dozens of almost
    # coincident tires can consume excessive RAM and stall a desktop.
    # A capsule covers the full continuous downward travel at each angle.
    capsules=[]
    for degrees in range(-30,31,5):
        lo=cylinder(47.5,42,(center.x-21,center.y,8),(1,0,0))
        hi=cylinder(47.5,42,(center.x-21,center.y,31),(1,0,0))
        bridge=box(center.x-21,center.y-47.5,8,42,95,23)
        capsule=lo.fuse(hi).fuse(bridge).removeSplitter()
        capsule.rotate(pivot,V(0,0,1),degrees)
        capsules.append(capsule)
    return capsules


def cut_motion(shape, tools):
    # Deliberately serial, bounded-size cuts. Never union the complete sweep.
    for tool in tools:
        a,b=shape.optimalBoundingBox(),tool.optimalBoundingBox()
        if min(a.XMax,b.XMax)>max(a.XMin,b.XMin) and min(a.YMax,b.YMax)>max(a.YMin,b.YMin) and min(a.ZMax,b.ZMax)>max(a.ZMin,b.ZMin):
            shape=shape.cut(tool).removeSplitter()
    return shape


def make_parts():
    print('Building smooth exterior',flush=True)
    outer=loft()
    print('Building thin inner surface',flush=True)
    cavity=loft(P['wall'])
    skin=outer.cut(cavity).removeSplitter()
    raw_skin=skin.copy()
    cuts=[]
    wheel_reserves=[]
    for y in (-32.5,-301):
        # Capsule in Y/Z: maximum compression at current Z plus 3 mm;
        # the rest of the allowed movement is downward from that pose.
        lo=cylinder(48.5,140,(92,y,8),(1,0,0))
        hi=cylinder(48.5,140,(92,y,31),(1,0,0))
        bridge=box(92,y-48.5,8,140,97,23)
        arch=lo.fuse(hi).fuse(bridge).removeSplitter()
        wheel_reserves.extend([arch,mirrored(arch)])
    print('Preparing separate motion capsules',flush=True)
    motion=front_motion_reserve()
    motion_tools=motion+[mirrored(t) for t in motion]
    # Open side windows, separated by a full B-pillar. Extrude from inside
    # the side skin outward; this avoids cutting the opposite roof/floor.
    front_window=[(-109,79),(-157,108),(-196,109),(-196,72),(-122,71)]
    quarter_window=[(-205,72),(-205,109),(-221,101),(-242,78),(-235,71)]
    for window in (front_window,quarter_window):
        c=prism([(43,y,z) for y,z in window],(125,0,0))
        cuts.extend([c,mirrored(c)])
        if window is quarter_window:quarter_panel=raw_skin.common(c).removeSplitter()
    windscreen=prism([(-65,-106,78),(65,-106,78),(49,-146,78),(-49,-146,78)],(0,0,80))
    rear_window=prism([(-46,-219,80),(46,-219,80),(56,-246,80),(-56,-246,80)],(0,0,70))
    cuts.extend([windscreen,rear_window])
    # Roof vent opening accepts a separate grille; support-free when printed flat.
    cuts.append(box(-22,-193,103,44,28,35))
    # Hood vents: four center louvers plus two diagonal groups.
    for y in (-78,-70,-62,-54):
        cuts.append(box(-21,y,68,42,4,25))
    for sign in (-1,1):
        for y in (-40,-32,-24):
            c=prism([(34,y,65),(56,y+4,65),(56,y+7,65),(34,y+3,65)],(0,0,35))
            cuts.append(c if sign>0 else mirrored(c))
    # Front trapezoid grille and angular headlight recesses in the flat nose.
    grille_outline=[(-42,44,45),(42,44,45),(32,44,22),(-32,44,22)]
    cuts.append(prism([(x,39,z) for x,y,z in grille_outline],(0,12,0)))
    light_poly=[(43,34),(58,37),(61,46),(41,41)]
    light_cut=prism([(x,39,z) for x,z in light_poly],(0,12,0))
    cuts.extend([light_cut,mirrored(light_cut)])
    cuts.extend([cylinder(1.7,14,(x,38,19.5),(0,1,0)) for x in (-50,50)])
    # Open rear center below the lamps, as in the reference. No rear grille.
    tail_open=[(-61,-355,-10),(61,-355,-10),(61,-355,48),(44,-355,57),(-44,-355,57),(-61,-355,48)]
    cuts.append(prism(tail_open,(0,23,0)))
    rear_light_poly=[(47,60),(88,60),(101,68),(99,73),(47,72)]
    rc=prism([(x,-355,z) for x,z in rear_light_poly],(0,11,0))
    cuts.extend([rc,mirrored(rc)])
    skin=cut_many(skin,cuts)
    # Four internal mounting pads. They sit outside the steering reserve and
    # connect only to the skirt; detachable brackets bridge to existing holes.
    pads=[]
    for y in P['mount_y']:
        p=box(72,y-7,11,16,14,2.2)
        pads.extend([p,mirrored(p)])
    skin=skin.multiFuse(pads).removeSplitter()
    fixing=[]
    for y in P['mount_y']:
        for x in (-P['mount_x'],P['mount_x']):fixing.append(hole_z(x,y,8,9))
    # Four roof mounting tabs and matching roof screws.
    roof_tabs=[]
    for y in (-148,-200.5):
        tab=box(49,y-4,101,28,8,4)
        roof_tabs.extend([tab,mirrored(tab)])
    skin=skin.multiFuse(roof_tabs).removeSplitter()
    for y in (-148,-200.5):
        for x in (-55,55):fixing.append(hole_z(x,y,100,25))
    for x in (-44,44):fixing.append(hole_z(x,-338,62,20))
    print('Cutting static clearance tools',flush=True)
    skin=cut_many(skin,fixing+wheel_reserves)
    print('Cutting serial steering envelopes',flush=True)
    skin=cut_motion(skin,motion_tools)
    # Separate removable roof before dividing the skirt into six sections.
    roof=skin.common(box(-180,-260,P['roof_split_z']+.15,360,180,45)).removeSplitter()
    add('Roof_cap',roof,(180,0,0),'Exterior roof flat against the build plate; four M3 screws into separate nuts below tabs.',
        'No broad internal roof support; small support at the intake/vent rim only if needed')
    lower=skin.cut(box(-180,-260,P['roof_split_z']-.15,360,180,50))
    ranges=[('Nose',-89.85,46),('Cab',-245.85,-90.15),('Tail',-351,-246.15)]
    for label,ya,yb in ranges:
        for side,x0,x1 in [('L',-160,-.15),('R',.15,160)]:
            s=lower.common(box(x0,ya,-10,x1-x0,yb-ya,170)).removeSplitter()
            # Print on the broad transverse split face; cab printed rear face down.
            # Nose rear face down; tail front face down.
            rotation=(-90,0,0) if label!='Tail' else (90,0,0)
            add(label+'_'+side,s,rotation,'Transverse seam face on bed; glue shell sections using the separate inner splice strips.',
                'Paint-on support only below isolated fender lips and window corners; avoid filling the open cabin')
    # Conformal backing strips sit 0.25 mm inside the shell for adhesive.
    backing=loft(P['wall']+.4).cut(loft(P['wall']+1.2))
    backing=cut_many(backing,cuts+wheel_reserves)
    backing=cut_motion(backing,motion_tools)
    for label,y in [('Front',-90),('Rear',-246)]:
        for side,x0,x1 in [('L',-96,-67),('R',67,96)]:
            s=backing.common(box(x0,y-8,16,x1-x0,16,60)).removeSplitter()
            usable=[q for q in s.Solids if q.Volume>50 and q.BoundBox.YMin<y-.15 and q.BoundBox.YMax>y+.15]
            if not usable:raise RuntimeError('No useful splice at '+str((label,side)))
            # Keep the useful continuous bridge, not small incidental slivers.
            usable=[max(usable,key=lambda q:q.Volume)]
            for i,q in enumerate(usable):
                add('Splice_'+label+'_'+side+str(i+1),q,(0,90 if side=='R' else -90,0),
                    'Conformal inner seam backing; 0.4 mm glue allowance per shell face. Mark seam center before gluing.',
                    'Small local supports if needed; print with broad curved face down')
    # Centerline bridges on solid hood/tail regions (not across open windows).
    for label,ya,yb,z0 in [('Nose',-10,14,60),('Tail',-337,-311,58)]:
        s=backing.common(box(-9,ya,z0,18,yb-ya,35)).removeSplitter()
        add('Splice_center_'+label,s,(180,0,0),'Glue beneath centerline; do not cover louvers.','None or very small edge support')
    # Chassis mounting brackets: bolt below existing plate holes and rise
    # outside the plate/table, leaving the central mechanism free.
    for yi,y in enumerate(P['mount_y']):
        base=box(60.4,y-7,-3,15.6,14,3)
        upright=box(71.5,y-6,0,2.0,12,8.4)
        foot=box(71.5,y-6,8.4,10.0,12,2.6)
        bracket=base.fuse(upright).fuse(foot)
        bracket=cut_many(bracket,[hole_z(66.4,y,-5,8),hole_z(P['mount_x'],y,7,8)]+wheel_reserves)
        for side,s in [('R',bracket),('L',mirrored(bracket))]:
            add(f'Mount_{yi+1}_{side}',s,(0,90 if side=='R' else -90,0),
                'M3 through existing chassis corner hole; M3 screw through shell pad and bracket into a loose nut below the foot. Longer lower screws share electronics-table fixing.',
                'Only small horizontal screw-hole bridges; print the L profile on its side')
    # Separate screw spacers prevent the roof from being pulled down onto
    # its tabs. Their tops follow the inner roof's exact sloping surface.
    for i,y in enumerate((-148,-200.5)):
        for side,x in [('L',-55),('R',55)]:
            spacer=cylinder(3.6,20,(x,y,105)).common(cavity)
            spacer=spacer.cut(hole_z(x,y,104,24))
            add(f'Roof_spacer_{i+1}_{side}',spacer,(0,0,0),
                'Bottom sits on cab tab; contoured top supports roof. Keep numbered front/rear pairs distinct.', 'None')
    # Flat roof grille, with a perimeter flange below the roof opening.
    rim=loft(P['wall']+.2).cut(loft(P['wall']+1.2)).common(box(-24,-195,103,48,32,25)).removeSplitter()
    ventholes=[]
    for x in range(-18,19,6):
        for y in range(-189,-168,7):
            ventholes.append(box(x-1.7,y,102,3.4,4.2,30))
    grille=cut_many(rim,ventholes)
    add('Roof_vent_grille',grille,(180,0,0),'Glue flange beneath vent opening; top recessed slightly below roof.','None')
    # Front grille in the same angular trapezoid as the reference.
    grille=prism([(x,43.85,z) for x,y,z in grille_outline],(0,1.0,0))
    holes=[]
    for row,z in enumerate(range(26,43,5)):
        for x in range(-34,35,6):
            cx=x+(3 if row%2 else 0)
            hp=[(cx+2.3*math.cos(i*math.pi/3),42,z+2.3*math.sin(i*math.pi/3)) for i in range(6)]
            h=prism(hp,(0,5,0))
            if all(abs(q[0])<31 for q in hp):holes.append(h)
    grille=cut_many(grille,holes)
    add('Front_grille',grille,(90,0,0),'Glue in nose aperture; small seam gap around perimeter.','None')
    for side,mirror in [('R',False),('L',True)]:
        lens=prism([(x,43.85,z) for x,z in light_poly],(0,1.0,0))
        # Raised inner optic motif is geometry, not a color assignment.
        detail=prism([(44,44.85,37),(56,44.85,39),(58,44.85,43),(43,44.85,40)],(0,.45,0))
        lens=lens.fuse(detail)
        add('Headlight_'+side,mirrored(lens) if mirror else lens,(90,0,0),'White printable cosmetic headlight insert; paint later if desired.','None')
    # Honeycomb rear-quarter inserts, following the sloped window surround.
    def in_polygon(y,z,poly):
        inside=False
        j=len(poly)-1
        for i in range(len(poly)):
            yi,zi=poly[i];yj,zj=poly[j]
            if (zi>z)!=(zj>z) and y<(yj-yi)*(z-zi)/(zj-zi)+yi:inside=not inside
            j=i
        return inside
    quarter_holes=[]
    for row,z in enumerate(range(76,111,7)):
        for yy in range(-238,-209,7):
            y=yy+(3.5 if row%2 else 0)
            vertices=[(y+2.3*math.cos(i*math.pi/3),z+2.3*math.sin(i*math.pi/3)) for i in range(6)]
            if all(in_polygon(vy+dy,vz+dz,quarter_window) for vy,vz in vertices for dy,dz in [(-1.5,0),(1.5,0),(0,-1.5),(0,1.5)]):
                quarter_holes.append(prism([(40,vy,vz) for vy,vz in vertices],(110,0,0)))
    quarter_panel=cut_many(quarter_panel,quarter_holes)
    for side,s in [('R',quarter_panel),('L',mirrored(quarter_panel))]:
        add('Quarter_grille_'+side,s,(0,90 if side=='R' else -90,0),
            'Sloped rear-quarter honeycomb insert; glue to window surround after assembling cab.',
            'Shallow local support under the curved outer face if needed')
    # Two inset rear lamp housings, with a raised C/hook signature matching
    # the reference. They can be painted after a single-filament white print.
    for side,is_mirrored in [('R',False),('L',True)]:
        lamp=prism([(x,-349.85,z) for x,z in rear_light_poly],(0,1.0,0))
        signature=[(52,63),(87,63),(96,69),(94,70.5),(52,69.5),
                   (52,67.5),(86,68.5),(90,67),(86,65),(52,65)]
        led=prism([(x,-349.85,z) for x,z in signature],(0,-.5,0))
        lamp=lamp.fuse(led)
        add('Rear_light_'+side,mirrored(lamp) if is_mirrored else lamp,(90,0,0),
            'Inset rear lamp housing with raised hook-shaped lens detail; glue into tail aperture.', 'None')
    # Separate angular front bumper, fixed to shell with two M3 screws.
    bumper=prism([(-77,45.2,16),(-70,57,16),(70,57,16),(77,45.2,16)],(0,0,7))
    bumper=bumper.cut(box(-54,48,21,108,7,8))
    bumper=cut_many(bumper,[cylinder(1.7,24,(x,39,19.5),(0,1,0)) for x in (-50,50)])
    add('Front_bumper',bumper,(0,0,0),'Two M3 screws along Y through bumper and nose; nuts accessible inside open shell. A 0.2 mm gap allows paint/glue.','None; recess faces up')
    # Wing: flat underside, rear Gurney lip, separate end plates and pylons.
    wing=box(-118,-384,113,236,40,1.4).fuse(box(-118,-384,114.4,236,1.2,6))
    strakes=[prism([(x-.5,-381,114.4),(x-.5,-349,114.4),(x-.5,-381,119.4)],(1,0,0)) for x in (-60,0,60)]
    wing=wing.multiFuse(strakes).removeSplitter()
    wing=cut_many(wing,[hole_z(x,-356,109,12) for x in (-44,44)])
    add('Rear_wing',wing,(0,0,0),'Flat bottom on bed; 236 mm span leaves 10 mm total allowance inside the 246 mm design envelope.','None')
    for side,xc in [('L',-117.4),('R',117.4)]:
        plate=prism([(xc-.6,-386,110),(xc-.6,-386,136),(xc-.6,-362,136),(xc-.6,-341,124),(xc-.6,-341,110)],(1.2,0,0))
        plate=cut_many(plate,[box(xc-2,-384.2,112.8,4,40.4,1.8),box(xc-2,-384.2,112.8,4,1.6,7.8)])
        add('Wing_endplate_'+side,plate,(0,90,0),'Glue over wing ends; 0.2 mm slot clearance.','None; broad side on bed')
    for side,xc in [('L',-44),('R',44)]:
        # Base underside follows the local tail deck, with a glue/paint gap.
        ya,yb=-345,-331
        za,zb=roof_z(ya)+.2,roof_z(yb)+.2
        # Follow the real curved deck with a uniform 0.2 mm glue/paint gap.
        # A chord between its endpoints would cut into a convex deck.
        deck=outer.common(box(xc-7,ya,55,14,yb-ya,40))
        upper=deck.copy();upper.translate(V(0,0,2.6))
        lower=deck.copy();lower.translate(V(0,0,.2))
        base=upper.cut(lower).removeSplitter()
        web=prism([(xc-1,ya,za+1.5),(xc-1,yb,zb+1.5),(xc-1,-349,112),(xc-1,-363,112)],(2,0,0))
        top=box(xc-6,-363,110.6,12,14,2.4)
        pylon=base.fuse(web).fuse(top)
        pylon=cut_many(pylon,[hole_z(xc,-338,60,22),hole_z(xc,-356,110,8),
                                 hex_prism(xc,-356,108.0,6.0,2.8),
                                 cylinder(3.2,25,(xc,-338,roof_z(-338)+2.6))])
        add('Wing_pylon_'+side,pylon,(0,90,0),'M3 base screw through tail shell; M3 top screw through wing into side-loaded nut pocket; relieved base web clears lower screw head/driver.','Small ledge supports at feet only; upright web prints flat')
    return skin, wheel_reserves, motion_tools


def printable_shape(item):
    s=item['shape'].copy()
    rx,ry,rz=item['orientation']
    r=App.Rotation(V(0,0,1),rz).multiply(App.Rotation(V(0,1,0),ry)).multiply(App.Rotation(V(1,0,0),rx))
    s.Placement=App.Placement(V(0,0,0),r).multiply(s.Placement)
    # OCC loose boxes include untrimmed loft control points. Use the tight
    # box, otherwise trimmed pieces can be exported floating above the bed.
    b=s.optimalBoundingBox()
    p=V(10-b.XMin,10-b.YMin,-b.ZMin)
    s.translate(p)
    b=s.optimalBoundingBox()
    dims=[b.XLength,b.YLength,b.ZLength]
    if max(dims)>P['print_limit']+1e-6:raise RuntimeError(f"Print envelope exceeded: {item['name']} {dims}")
    item['print_size_mm']=[round(d,3) for d in dims]
    item['print_transform']={'rotation_quaternion':r.Q,'translation_mm':list(p)}
    return s


def create_document():
    if App.listDocuments().get('Fairing'):raise RuntimeError('Close Fairing before rebuilding')
    d=App.newDocument('Fairing');d.Label='Buggy fairing — segmented PLA shell'
    group=d.addObject('App::Part','Fairing');group.Label='Fairing — assembled positions (mm)'
    group.addProperty('App::PropertyString','ReferenceImage','Design').ReferenceImage='../../fairing.png'
    group.addProperty('App::PropertyString','DesignNotes','Design').DesignNotes='Lower, lightweight smooth-surface buggy shell; open windows; white PLA; see fairing/FAIRING.txt'
    group.addProperty('App::PropertyLength','Wall','Design').Wall=P['wall']
    group.addProperty('App::PropertyString','SteeringReserve','Design').SteeringReserve=str(P['steering_reserve'])+' mm; saver adds 20 mm along shaft plus 10 mm axial margin; diameter unknown'
    printgroup=d.addObject('App::Part','PrintOrientations');printgroup.Label='Print orientations (hidden; show alone)'
    for item in PARTS:
        obj=d.addObject('Part::Feature',item['name']);obj.Shape=item['shape'];group.addObject(obj)
        for key,value in [('AssemblyNote',item['note']),('PrintSupport',item['support']),('PrintEulerDegrees',str(item['orientation']))]:
            obj.addProperty('App::PropertyString',key,'Manufacturing');setattr(obj,key,value)
        ps=printable_shape(item)
        po=d.addObject('Part::Feature','Print_'+item['name']);po.Shape=ps;printgroup.addObject(po)
        obj.addProperty('App::PropertyString','PrintSizeMM','Manufacturing').PrintSizeMM=str(item['print_size_mm'])
        if App.GuiUp:
            obj.ViewObject.ShapeColor=(.87,.87,.85);obj.ViewObject.LineColor=(.25,.25,.24)
            obj.ViewObject.DisplayMode='Shaded';obj.ViewObject.LineWidth=1
            po.ViewObject.ShapeColor=(.87,.87,.85)
        mesh=MeshPart.meshFromShape(Shape=ps,LinearDeflection=.04,AngularDeflection=.12,Relative=False)
        if not mesh.isSolid():raise RuntimeError('Non-watertight STL '+item['name'])
        mesh.write(str(HERE/'print'/(item['name']+'.stl')))
        item['mesh_facets']=mesh.CountFacets
        print('EXPORT',item['name'],item['print_size_mm'],flush=True)
    refs=d.addObject('App::DocumentObjectGroup','ClearanceReferences')
    motion=d.addObject('Part::Feature','Front_steering_and_bump_reserve')
    motion.Shape=Part.makeCompound(MOTION_REFERENCES)
    refs.addObject(motion)
    x0,y0,z0,x1,y1,z1=P['steering_reserve']
    keep=d.addObject('Part::Feature','Steering_and_servo_saver_reserve')
    keep.Shape=box(x0,y0,z0,x1-x0,y1-y0,z1-z0);refs.addObject(keep)
    if App.GuiUp:
        keep.ViewObject.ShapeColor=(1,.45,.12);keep.ViewObject.Transparency=75
        keep.ViewObject.Visibility=False;motion.ViewObject.Visibility=False;refs.ViewObject.Visibility=False;printgroup.ViewObject.Visibility=False
    d.recompute();d.saveAs(str(CAD/'fairing.FCStd'))
    return d


def install_into_assembly(doc):
    """Embed printable components. Never add a cross-document link or solver."""
    old=doc.getObject('Fairing')
    if old:
        for o in list(old.Group):doc.removeObject(o.Name)
        doc.removeObject(old.Name)
    opened=False
    fp=CAD/'fairing.FCStd'
    src=next((d for d in App.listDocuments().values() if d.FileName and Path(d.FileName).resolve()==fp.resolve()),None)
    if src is None:src=App.openDocument(str(fp));opened=True
    group=doc.addObject('App::Part','Fairing');group.Label='04 Fairing — white PLA (toggle visibility)'
    root=doc.getObject('Car')
    if root:root.addObject(group)
    for source in src.getObject('Fairing').Group:
        obj=doc.addObject('Part::Feature','Fairing_'+source.Name);obj.Label=source.Label
        obj.Shape=source.Shape.copy();group.addObject(obj)
        obj.addProperty('App::PropertyString','SourceFile','Reference').SourceFile='fairing.FCStd / '+source.Name
        if App.GuiUp:
            obj.ViewObject.ShapeColor=(.87,.87,.85);obj.ViewObject.LineColor=(.24,.24,.23);obj.ViewObject.DisplayMode='Shaded';obj.ViewObject.LineWidth=1
    doc.recompute()
    if opened:App.closeDocument(src.Name)
    App.setActiveDocument(doc.Name)
    return group


def main():
    (HERE/'print').mkdir(exist_ok=True)
    global MOTION_REFERENCES
    _,wheel_reserves,MOTION_REFERENCES=make_parts()
    d=create_document()
    (HERE/'parameters.json').write_text(json.dumps(P,indent=2)+'\n')
    manifest=[{k:v for k,v in item.items() if k!='shape'} for item in PARTS]
    (HERE/'print_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('DONE fairing:',len(PARTS),'printable components',flush=True)
    return d

if __name__=='__main__':main()
