import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import convert, ConversionError, ConversionReview, worker, write_progress
import rhino3dm as r3
from OCP.STEPControl import STEPControl_Reader
from OCP.IFSelect import IFSelect_ReturnStatus
from serpentine3d.core import geometry


class Conversions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def model(self, geometry_list, units=r3.UnitSystem.Millimeters):
        model = r3.File3dm()
        model.Settings.ModelUnitSystem = units
        for geo in geometry_list:
            model.Objects.Add(geo, r3.ObjectAttributes())
        path = self.root/'sample.3dm'
        self.assertTrue(model.Write(str(path), 6))
        return path

    def box(self):
        return r3.BoundingBox(r3.Point3d(0,0,0),r3.Point3d(1,2,3)).ToBrep()

    def test_six_formats_and_step_dimensions(self):
        source = self.model([self.box()], r3.UnitSystem.Inches)
        digest = hashlib.sha256(source.read_bytes()).digest()
        result = convert(source, self.root/'out', ['step','iges','brep','stl','obj','ply'])
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(len(result['outputs']), 6)
        for output in result['outputs']:
            fmt = output['format']
            self.assertEqual(Path(output['path']).name, 'sample_' + fmt.upper() + '.' + fmt)
        self.assertEqual(digest, hashlib.sha256(source.read_bytes()).digest())
        step = Path(next(o['path'] for o in result['outputs'] if o['format']=='step'))
        reader = STEPControl_Reader()
        self.assertEqual(reader.ReadFile(str(step)), IFSelect_ReturnStatus.IFSelect_RetDone)
        reader.TransferRoots()
        shape = reader.OneShape()
        self.assertTrue(geometry.is_valid(shape))
        lo, hi = geometry.bbox(shape)
        for actual, expected in zip([hi[i]-lo[i] for i in range(3)], [25.4,50.8,76.2]):
            self.assertAlmostEqual(actual, expected, places=4)
        self.assertAlmostEqual(geometry.volume(shape),25.4*50.8*76.2,places=2)

    def test_sphere_roundtrip_solid_and_volume(self):
        source = self.model([r3.Sphere(r3.Point3d(0,0,0),5).ToBrep()])
        result = convert(source,self.root/'out',['step'])
        self.assertEqual(result['status'],'complete')
        reader=STEPControl_Reader()
        reader.ReadFile(result['outputs'][0]['path']); reader.TransferRoots()
        import math
        self.assertAlmostEqual(geometry.volume(reader.OneShape()),4/3*math.pi*125,places=3)

    def test_trimmed_circle_has_correct_area(self):
        import math
        circle=r3.Circle(r3.Point3d(0,0,0),5).ToNurbsCurve()
        disk=r3.Brep.CreateTrimmedPlane(r3.Plane.WorldXY(),circle)
        source=self.model([disk])
        result=convert(source,self.root/'out',['step'])
        self.assertEqual(result['status'],'complete')
        reader=STEPControl_Reader(); reader.ReadFile(result['outputs'][0]['path']); reader.TransferRoots()
        # The trim reader reconstructs boundary curves; require area agreement
        # within 0.01%, rather than claiming an exact symbolic circle.
        self.assertAlmostEqual(geometry.surface_area(reader.OneShape()),math.pi*25,delta=math.pi*25*0.0001)

    def test_placed_block_does_not_duplicate_definition_at_origin(self):
        model=r3.File3dm(); model.Settings.ModelUnitSystem=r3.UnitSystem.Millimeters
        index=model.InstanceDefinitions.Add('Test block','','','',r3.Point3d(0,0,0),(self.box(),),(r3.ObjectAttributes(),))
        definition=model.InstanceDefinitions[index]
        model.Objects.AddInstanceObject(r3.InstanceReference(definition.Id,r3.Transform.Translation(20,0,0)),r3.ObjectAttributes())
        source=self.root/'block.3dm'; model.Write(str(source),6)
        result=convert(source,self.root/'out',['step'])
        self.assertEqual(result['counts']['converted_objects'],1)
        reader=STEPControl_Reader(); reader.ReadFile(result['outputs'][0]['path']); reader.TransferRoots()
        lo,hi=geometry.bbox(reader.OneShape())
        self.assertAlmostEqual(lo[0],20,places=4)
        self.assertAlmostEqual(hi[0],21,places=4)

    def test_mesh_blocks_exact_export_but_writes_mesh(self):
        mesh=r3.Mesh()
        for v in [(0,0,0),(1,0,0),(0,1,0)]: mesh.Vertices.Add(*v)
        mesh.Faces.AddFace(0,1,2)
        source=self.model([mesh])
        result=convert(source,self.root/'out',['step','obj'])
        self.assertEqual(result['status'],'partial')
        self.assertIn('step',result['format_errors'])
        self.assertEqual([o['format'] for o in result['outputs']],['obj'])

    def test_hidden_and_curve_exclusions_reported(self):
        model=r3.File3dm(); model.Settings.ModelUnitSystem=r3.UnitSystem.Millimeters
        hidden=r3.ObjectAttributes(); hidden.Visible=False
        model.Objects.AddBrep(self.box())
        model.Objects.AddBrep(self.box(),hidden)
        model.Objects.AddCurve(r3.LineCurve(r3.Point3d(0,0,0),r3.Point3d(2,0,0)))
        source=self.root/'sample.3dm'; model.Write(str(source),6)
        result=convert(source,self.root/'out',['step'],{'exclude_curves':True})
        self.assertEqual(result['counts']['excluded_hidden'],1)
        self.assertEqual(result['counts']['excluded_curves'],1)
        self.assertEqual(result['counts']['converted_objects'],1)

    def test_no_overwrite_and_unitless_rejected(self):
        source=self.model([self.box()])
        a=convert(source,self.root/'out',['brep'])
        b=convert(source,self.root/'out',['brep'])
        self.assertNotEqual(a['folder'],b['folder'])
        source=self.model([self.box()],getattr(r3.UnitSystem,'None'))
        with self.assertRaises(ConversionError): convert(source,self.root/'out',['step'])

    def test_worker_failure_and_success(self):
        source=self.model([self.box()])
        job=self.root/'job.json'
        def run(path):
            job.write_text(json.dumps({'source':str(path),'destination':str(self.root/'out'),'formats':['brep'],'options':{}}))
            subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/'app.py'),'--worker',str(job)],check=True,capture_output=True,timeout=90)
            return json.loads(job.with_suffix('.result.json').read_text())
        self.assertEqual(run(source)['status'],'complete')
        self.assertEqual(run(self.root/'missing.3dm')['status'],'failed')

    def test_progress_retries_windows_lock_and_publishes_latest_state(self):
        import os
        state = self.root/'job.state.json'
        state.write_text(json.dumps({'progress': 0, 'message': 'Starting'}))
        original_replace = os.replace
        calls = []
        def replace(source, destination):
            calls.append(destination)
            if len(calls) < 3:
                raise PermissionError(13, 'Access is denied')
            return original_replace(source, destination)
        with patch('engine.os.replace', side_effect=replace), patch('engine.time.sleep'):
            self.assertTrue(write_progress(state, 0.5, 'Writing STEP'))
        self.assertEqual(len(calls), 3)
        self.assertEqual(json.loads(state.read_text()), {'progress': 0.5, 'message': 'Writing STEP'})

    def test_locked_progress_temporary_file_is_nonfatal(self):
        state = self.root/'job.state.json'
        with patch('engine.Path.write_text', side_effect=PermissionError(13, 'Access is denied')), patch('engine.time.sleep'):
            self.assertFalse(write_progress(state, 0.5, 'Writing STEP'))
        self.assertFalse(state.with_suffix('.tmp').exists())

    def test_worker_exports_when_progress_remains_locked(self):
        import os
        source = self.model([self.box()])
        digest = hashlib.sha256(source.read_bytes()).digest()
        job = self.root/'job.json'
        job.write_text(json.dumps({'source': str(source), 'destination': str(self.root/'out'),
                                   'formats': ['step', 'stl'], 'options': {}}))
        state = job.with_suffix('.state.json')
        state.write_text(json.dumps({'progress': 0, 'message': 'Starting'}))
        original_replace = os.replace
        def replace(source_path, destination):
            if Path(destination) == state:
                raise PermissionError(13, 'Access is denied')
            return original_replace(source_path, destination)
        with patch('engine.os.replace', side_effect=replace), patch('engine.time.sleep'):
            worker(job)
        result = json.loads(job.with_suffix('.result.json').read_text())
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(len(result['outputs']), 2)
        for output in result['outputs']:
            self.assertGreater(Path(output['path']).stat().st_size, 0)
        self.assertTrue((Path(result['folder'])/'conversion-report.json').is_file())
        self.assertEqual(digest, hashlib.sha256(source.read_bytes()).digest())
        self.assertFalse(state.with_suffix('.tmp').exists())

    def test_worker_still_reports_export_write_failures(self):
        import os
        source = self.model([self.box()])
        job = self.root/'job.json'
        job.write_text(json.dumps({'source': str(source), 'destination': str(self.root/'out'),
                                   'formats': ['brep'], 'options': {}}))
        original_replace = os.replace
        def replace(source_path, destination):
            if Path(destination).suffix == '.brep':
                raise PermissionError(13, 'Access is denied')
            return original_replace(source_path, destination)
        with patch('engine.os.replace', side_effect=replace):
            worker(job)
        result = json.loads(job.with_suffix('.result.json').read_text())
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['outputs'], [])
        self.assertIn('Access is denied', result['format_errors']['brep'])

    def test_annotations_and_curves_skipped_by_default(self):
        source=self.model([self.box(),r3.LineCurve(r3.Point3d(0,0,0),r3.Point3d(5,0,0)),r3.TextDot('Dimension note',r3.Point3d(0,0,0))])
        digest=hashlib.sha256(source.read_bytes()).digest()
        result=convert(source,self.root/'out',['step'])
        self.assertEqual(result['counts']['excluded_curves'],1)
        self.assertEqual(result['counts']['annotations'],1)
        self.assertEqual(result['counts']['converted_objects'],1)
        self.assertTrue(result['converted_from_temporary_copy'])
        self.assertEqual(digest,hashlib.sha256(source.read_bytes()).digest())
        # The user's DimLinear failure is an AnnotationBase subclass, unlike
        # the original name-based filter that only recognized TextDot.
        self.assertTrue(issubclass(r3.DimLinear,r3.AnnotationBase))
        self.assertTrue(issubclass(r3.DimAngular,r3.AnnotationBase))

    def test_convert_anyway_reports_omissions_and_keeps_source(self):
        cloud=r3.PointCloud(); cloud.Add(r3.Point3d(7,8,9))
        source=self.model([self.box(),cloud])
        digest=hashlib.sha256(source.read_bytes()).digest()
        with self.assertRaises(ConversionReview):
            convert(source,self.root/'out',['step'])
        result=convert(source,self.root/'out',['step'],{'allow_partial':True})
        self.assertEqual(result['status'],'partial')
        self.assertEqual(len(result['outputs']),1)
        self.assertEqual(result['counts']['skipped_unsupported'],1)
        self.assertIn('PointCloud',result['skipped_objects'][0])
        self.assertEqual(digest,hashlib.sha256(source.read_bytes()).digest())

    def test_custom_name_folder_and_existing_results_preserved(self):
        source=self.model([self.box()])
        first=convert(source,self.root/'out',['brep'],{'output_name':'Office fixture'})
        previous=Path(first['outputs'][0]['path']).read_bytes()
        second=convert(source,self.root/'out',['brep'],{'output_name':'Office fixture'})
        self.assertEqual(Path(first['folder']).name,'Office fixture')
        self.assertEqual(Path(second['folder']).name,'Office fixture (2)')
        self.assertEqual(Path(first['outputs'][0]['path']).name,'Office fixture_BREP.brep')
        self.assertEqual(Path(first['outputs'][0]['path']).read_bytes(),previous)
        for name in ['../escape','bad/name','CON','lamp.']:
            with self.assertRaises(ConversionError):
                convert(source,self.root/'out',['brep'],{'output_name':name})


if __name__=='__main__': unittest.main()
