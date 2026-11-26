"""Render native CAD previews with FreeCAD's GUI runtime (no image generation).
Run via FreeCAD's Python runtime. Use a two-core process for this project.
"""
from pathlib import Path
import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

CAD=Path(__file__).resolve().parent.parent
OUT=CAD/'fairing-preview'
VIEWS={
    'isometric':(.4247082003,.1759198966,.3398511430,.8204732386),
    'front-isometric':(.1759198966,.4247082003,.8204732386,.3398511430),
    'top':(0,0,0,1), 'side':(.5,.5,.5,.5),
    'front':(0,2**-.5,2**-.5,0), 'rear':(2**-.5,0,0,2**-.5),
}

def opened(path):
    d=next((d for d in App.listDocuments().values() if d.FileName and Path(d.FileName).resolve()==path.resolve()),None)
    return d or App.openDocument(str(path))

def paint(obj,lines=False):
    if 'AlreadyPrinted' not in obj.PropertiesList:
        obj.addProperty('App::PropertyBool','AlreadyPrinted','Manufacturing')
    obj.AlreadyPrinted=obj.Name.removeprefix('Fairing_') in ('Rear_wing','Front_bumper')
    obj.ViewObject.ShapeColor=(.84,.84,.82)
    obj.ViewObject.LineColor=(.28,.28,.26)
    obj.ViewObject.DisplayMode='Flat Lines' if lines or 'Rear_light' in obj.Name or 'Headlight' in obj.Name else 'Shaded'
    obj.ViewObject.LineWidth=1
    obj.ViewObject.Visibility=True

def view(doc,name,path):
    App.setActiveDocument(doc.Name);QApplication.processEvents()
    v=Gui.getDocument(doc.Name).activeView()
    v.setCameraOrientation(VIEWS[name]);QTest.qWait(600)
    v.fitAll();QApplication.processEvents();v.redraw()
    v.saveImage(str(path),1800,1200,'White')

def main():
    OUT.mkdir(exist_ok=True)
    had_gui=bool(App.GuiUp)
    Gui.showMainWindow();Gui.activateWorkbench('PartWorkbench')
    if not had_gui:Gui.getMainWindow().hide()
    f=opened(CAD/'fairing.FCStd')
    f.getObject('Fairing').ViewObject.Visibility=True
    for o in f.getObject('Fairing').Group:paint(o)
    f.getObject('PrintOrientations').ViewObject.Visibility=False
    f.getObject('ClearanceReferences').ViewObject.Visibility=False
    for o in f.getObject('ClearanceReferences').Group:o.ViewObject.Visibility=False
    view(f,'front-isometric',OUT/'body-only.png');f.save()
    a=opened(CAD/'full_assembly.FCStd')
    a.getObject('Car').ViewObject.Visibility=True
    for name in ['FrontModule','MiddleModule','RearModule','Fairing']:
        a.getObject(name).ViewObject.Visibility=True
        for o in a.getObject(name).Group:o.ViewObject.Visibility=True
    for o in a.getObject('Fairing').Group:paint(o)
    for name in VIEWS:view(a,name,OUT/(name+'.png'))
    view(a,'front-isometric',OUT/'front-isometric.png');a.save()
    e=App.newDocument('FairingExploded')
    for source in f.getObject('Fairing').Group:
        name=source.Name;o=e.addObject('Part::Feature',name);o.Shape=source.Shape.copy()
        delta=App.Vector(0,0,0)
        if name.startswith(('Nose_','Join_Nose_','Headlight_','Front_grille','Front_bumper')):delta.y=35
        if name.startswith(('Tail_','Rear_light')):delta.y=-35
        if name in ['Roof_cap','Roof_vent_grille']:delta.z=40
        if name.startswith('Roof_spacer'):delta.z=18
        if name.startswith(('Rear_wing','Wing_')):delta.z=20;delta.y=-35
        if name.startswith(('Nose_hood','Tail_deck')):delta.z+=20
        if name.startswith('Cab_frame'):delta.z+=18
        if 'fender_aft' in name:delta.y-=10
        if 'fender_fore' in name:delta.y+=10
        if name.startswith('Nose_cheek'):delta.y+=22
        if name.endswith('_L') or '_L1' in name:delta.x=-22
        if name.endswith('_R') or '_R1' in name:delta.x=22
        o.Placement.Base=o.Placement.Base+delta;paint(o,True)
    e.recompute();view(e,'front-isometric',OUT/'exploded.png')
    p=App.newDocument('NosePrintOrientations')
    for name,x,y in [('Nose_hood_R',0,0),('Nose_fender_aft_R',100,0),('Nose_fender_fore_R',100,105),('Nose_cheek_R',175,0),('Join_Nose_cheek_R',175,105)]:
        source=f.getObject('Print_'+name)
        o=p.addObject('Part::Feature',name);o.Shape=source.Shape.copy()
        b=o.Shape.optimalBoundingBox()
        o.Placement.Base+=App.Vector(x-b.XMin,y-b.YMin,-b.ZMin)
        paint(o,True)
    p.recompute();view(p,'front-isometric',OUT/'nose-print-orientations.png')
    App.closeDocument(p.Name)
    App.closeDocument(e.Name);App.setActiveDocument(a.Name)
    print('Rendered assembled, rear, isolated and exploded previews.',flush=True)

if __name__=='__main__':main()
