"""Offline 3DM conversion. No Rhino process, license, service or network calls."""
from pathlib import Path
import json
import math
import os
import shutil
import re
import struct
import sys
import tempfile
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parent / 'vendor'))
FORMATS = {
    'step': ('STEP', 'CAD surfaces and solids'),
    'iges': ('IGES', 'CAD surfaces and curves'),
    'brep': ('BREP', 'Open Cascade geometry'),
    'stl': ('STL', 'Triangle mesh; millimetres'),
    'obj': ('OBJ', 'Triangle mesh with object names; millimetres'),
    'ply': ('PLY', 'Triangle mesh; millimetres'),
}


class ConversionError(Exception):
    pass


class ConversionReview(ConversionError):
    def __init__(self, issues):
        self.issues = issues
        super().__init__('Some objects could not be converted.\n' + '\n'.join(issues))


def output_name(value):
    if not isinstance(value, str) or not value or len(value) > 180:
        raise ConversionError('Choose an output name between 1 and 180 characters.')
    if re.search(r'[<>:"/\\|?*\x00-\x1f]', value) or value.endswith(('.', ' ')) or value in ('.', '..'):
        raise ConversionError('The output name contains characters Windows cannot use in filenames.')
    if value.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*('COM'+str(i) for i in range(1,10)),*('LPT'+str(i) for i in range(1,10))}:
        raise ConversionError('That name is reserved by Windows. Choose a different output name.')
    return value


def result_folder(destination, name):
    for number in range(1, 10001):
        path = destination/(name if number == 1 else '%s (%s)' % (name, number))
        try:
            path.mkdir()
            return path
        except FileExistsError:
            continue
    raise ConversionError('Too many result folders already use that name.')


def load_geometry(source, options, progress):
    import numpy as np
    import rhino3dm as r3
    from serpentine3d.fileio import rhino
    from serpentine3d.core import geometry, occ
    from serpentine3d.core.mesh import MeshShape
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer

    model = r3.File3dm.Read(str(source))
    if model is None:
        raise ConversionError('This file could not be read as a Rhino 3DM model.')
    box = r3.BoundingBox(r3.Point3d(0, 0, 0), r3.Point3d(1, 1, 1)).ToBrep()
    if not hasattr(box.Faces[0], 'OuterLoop'):
        raise ConversionError('The engine needs rhino3dm 8.32 or newer for trimmed surfaces.')
    units = model.Settings.ModelUnitSystem
    if units in (getattr(r3.UnitSystem, 'None'), r3.UnitSystem.Unset, r3.UnitSystem.CustomUnits):
        raise ConversionError('The model has no standard length unit. Assign units before conversion.')
    scale = r3.UnitSystem.UnitScale(units, r3.UnitSystem.Millimeters)
    if not math.isfinite(scale) or scale <= 0:
        raise ConversionError('Unsupported model units.')
    layers = rhino.read_layers(model)
    blocks = rhino.read_blocks(model)
    matrix = np.eye(4)
    matrix[:3, :3] *= scale
    output, issues, warnings = [], [], []
    counts = {'source_objects': 0, 'converted_objects': 0, 'excluded_hidden': 0,
              'excluded_curves': 0, 'annotations': 0, 'mesh_objects': 0,
              'skipped_unsupported': 0}

    def is_hidden(attrs):
        meta = rhino.object_appearance(attrs, layers, {})
        return (not meta.get('visible', True) or not meta.get('layer_visible', True)
                or any(not parent.get('visible', True) for parent in meta.get('layer_chain', ())))

    def block_members(instance, placement=None, ancestors=(), parent_hidden=False):
        key = str(instance.ParentIdefId)
        if key in ancestors or len(ancestors) >= 32:
            raise ConversionError('A block contains a cycle or exceeds 32 nesting levels.')
        definition = blocks.get(key)
        if not definition or not definition['members']:
            raise ConversionError('A block definition is missing or empty.')
        here = rhino._xform_matrix(instance.Xform)
        transform = here if placement is None else placement @ here
        for geo, attrs in definition['members']:
            hidden = parent_hidden or is_hidden(attrs)
            if isinstance(geo, r3.InstanceReference):
                yield from block_members(geo, transform, ancestors+(key,), hidden)
            else:
                yield geo, attrs, transform, hidden

    def face_count(shape):
        exp = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_FACE)
        n = 0
        while exp.More():
            n += 1
            exp.Next()
        return n

    def add(geo, attrs, name, placement=None):
        if not options.get('include_hidden') and is_hidden(attrs):
            counts['excluded_hidden'] += 1
            return
        if options.get('exclude_curves', True) and isinstance(geo, r3.Curve):
            counts['excluded_curves'] += 1
            return
        counts['source_objects'] += 1
        # Text and lights are not CAD geometry; record their omission explicitly.
        if (isinstance(geo, r3.AnnotationBase)
                or geo.ObjectType in (r3.ObjectType.Annotation, r3.ObjectType.TextDot,
                                      r3.ObjectType.Light, r3.ObjectType.Hatch,
                                      r3.ObjectType.Detail, r3.ObjectType.ClipPlane)):
            counts['annotations'] += 1
            warnings.append(name + ': ' + type(geo).__name__ + ' annotation/reference object skipped.')
            return
        try:
            shapes = rhino.object_to_shapes(geo)
            shapes = [s for s in shapes if s is not None and not s.IsNull()]
            if not shapes:
                raise ConversionError('unsupported or unreconstructed ' + type(geo).__name__)
            source_brep = geo.ToBrep(True) if isinstance(geo, r3.Extrusion) else geo
            if isinstance(source_brep, r3.Brep):
                if any(isinstance(s, MeshShape) for s in shapes):
                    raise ConversionError('a CAD face could only be recovered as a mesh')
                actual_faces = sum(face_count(s) for s in shapes)
                if actual_faces != len(source_brep.Faces):
                    raise ConversionError('face count changed (%s to %s)' % (len(source_brep.Faces), actual_faces))
                if source_brep.IsSolid and not all(geometry.shape_kind(s) == 'solid' for s in shapes):
                    raise ConversionError('a closed source solid became an open shell')
            transform = matrix if placement is None else matrix @ placement
            prepared = []
            meshes = 0
            for i, shape in enumerate(shapes):
                if isinstance(shape, MeshShape):
                    meshes += 1
                    shape = shape.transformed(transform)
                else:
                    if not geometry.is_valid(shape):
                        raise ConversionError('invalid reconstructed CAD geometry')
                    shape = geometry.apply_matrix(shape, transform)
                prepared.append((name if len(shapes) == 1 else name + ' ' + str(i+1), shape))
            output.extend(prepared)
            counts['mesh_objects'] += meshes
            counts['converted_objects'] += 1
        except Exception as exc:
            issues.append(name + ': ' + str(exc))

    for index, obj in enumerate(model.Objects):
        progress(0.05 + 0.65 * index / max(len(model.Objects), 1), 'Reading object %s of %s' % (index+1, len(model.Objects)))
        if obj.Attributes.IsInstanceDefinitionObject:
            continue
        name = obj.Attributes.Name or 'Object %s' % (index+1)
        if isinstance(obj.Geometry, r3.InstanceReference):
            try:
                for j, (geo, attrs, placement, hidden) in enumerate(block_members(obj.Geometry, parent_hidden=is_hidden(obj.Attributes))):
                    if not options.get('include_hidden') and hidden:
                        counts['excluded_hidden'] += 1
                        continue
                    add(geo, attrs, name + '/' + (attrs.Name or str(j+1)), placement)
            except Exception as exc:
                issues.append(name + ': ' + str(exc))
        else:
            add(obj.Geometry, obj.Attributes, name)
    if not output:
        raise ConversionError('No supported geometry remains after the selected exclusions.')
    if issues and not options.get('allow_partial'):
        raise ConversionReview(issues)
    if issues:
        warnings.extend('Skipped: ' + issue for issue in issues)
        counts['skipped_unsupported'] = len(issues)
    warnings += ['Assembly blocks are flattened into positioned objects; materials and Rhino history are not preserved.']
    warnings += ['Reconstructed CAD trims can introduce approximation errors; verify production geometry.']
    return output, {'source_units': str(units), 'output_units': 'millimetres', 'counts': counts, 'warnings': warnings,
                    'skipped_objects': issues, 'partial_conversion_authorized': bool(issues)}


def triangles(named, deviation):
    import numpy as np
    from serpentine3d.core.tessellate import tessellate
    vertices, faces, names = [], [], []
    offset = 0
    omitted = []
    for name, shape in named:
        mesh = tessellate(shape, deflection=deviation)
        if not mesh.has_faces:
            omitted.append(name)
            continue
        vertices.extend(mesh.vertices.tolist())
        tris = np.asarray(mesh.triangles, dtype=np.int64) + offset
        faces.extend(tris.tolist())
        names.extend([name] * len(tris))
        offset += len(mesh.vertices)
    if not faces:
        raise ConversionError('Mesh output requires surfaces or mesh objects. Curves and points cannot produce triangles.')
    return vertices, faces, names, omitted


def write_mesh(path, fmt, data):
    import numpy as np
    vertices, faces, names, omitted = data
    if fmt == 'stl':
        with path.open('wb') as stream:
            stream.write(b'Rhino Converter | coordinates in millimetres'.ljust(80, b' '))
            stream.write(struct.pack('<I', len(faces)))
            for face in faces:
                pts = np.asarray([vertices[i] for i in face])
                normal = np.cross(pts[1]-pts[0], pts[2]-pts[0])
                length = np.linalg.norm(normal)
                normal = normal/length if length else np.zeros(3)
                stream.write(struct.pack('<12fH', *normal, *pts.flatten(), 0))
    elif fmt == 'obj':
        with path.open('w', encoding='utf-8') as stream:
            stream.write('# Coordinates in millimetres\n')
            for v in vertices:
                stream.write('v %.12g %.12g %.12g\n' % tuple(v))
            current = None
            for face, name in zip(faces, names):
                if name != current:
                    stream.write('o ' + ''.join(c if c.isalnum() else '_' for c in name) + '\n')
                    current = name
                stream.write('f %s %s %s\n' % tuple(i+1 for i in face))
    else:
        with path.open('w', encoding='ascii') as stream:
            stream.write('ply\nformat ascii 1.0\ncomment units millimetres\nelement vertex %s\nproperty double x\nproperty double y\nproperty double z\nelement face %s\nproperty list uchar int vertex_indices\nend_header\n' % (len(vertices), len(faces)))
            for v in vertices:
                stream.write('%.12g %.12g %.12g\n' % tuple(v))
            for face in faces:
                stream.write('3 %s %s %s\n' % tuple(face))


def convert(source, destination, formats, options=None, progress=lambda value, text: None):
    from serpentine3d.core import geometry
    from serpentine3d.core.mesh import MeshShape
    from OCP.STEPControl import STEPControl_Writer, STEPControl_StepModelType
    from OCP.IGESControl import IGESControl_Writer
    from OCP.IFSelect import IFSelect_ReturnStatus
    from OCP.BRepTools import BRepTools
    from OCP.Interface import Interface_Static
    source, destination = Path(source), Path(destination)
    options = options or {}
    if not source.is_file() or source.suffix.lower() != '.3dm':
        raise ConversionError('Choose an existing .3dm file.')
    if not formats or any(f not in FORMATS for f in formats):
        raise ConversionError('Choose at least one supported output format.')
    basename = output_name(options.get('output_name') or source.stem)
    deviation = float(options.get('deviation', 0.1))
    if not math.isfinite(deviation) or not 0.001 <= deviation <= 10:
        raise ConversionError('Mesh deviation must be 0.001 to 10 millimetres.')
    destination.mkdir(parents=True, exist_ok=True)
    # Load only a disposable byte-for-byte copy. The source is never opened
    # for writing, even when the user authorizes a partial conversion.
    progress(0.01, 'Copying source file for conversion')
    with tempfile.TemporaryDirectory(prefix='rhino-converter-source-') as workspace:
        working_source = Path(workspace)/source.name
        shutil.copyfile(source, working_source)
        named, report = load_geometry(working_source, options, progress)
    report['original_untouched'] = True
    report['converted_from_temporary_copy'] = True
    report.update({'source': str(source), 'outputs': [], 'format_errors': {}, 'mesh_deviation_mm': deviation})
    exact = [s for _, s in named if not isinstance(s, MeshShape)]
    has_mesh = len(exact) != len(named)
    # A unique run folder never overwrites previous exports or the source.
    run = result_folder(destination, basename)
    report['output_name'] = basename
    mesh_data = None
    for i, fmt in enumerate(dict.fromkeys(formats)):
        progress(0.72 + 0.25 * i/len(formats), 'Writing ' + FORMATS[fmt][0])
        final = run/(basename + '_' + fmt.upper() + '.' + fmt)
        temp = run/('partial.' + fmt)
        try:
            if fmt in ('step', 'iges', 'brep'):
                if has_mesh:
                    raise ConversionError('The model contains meshes. Exact CAD export would omit them; choose a mesh format.')
                if fmt == 'step':
                    writer = STEPControl_Writer()
                    Interface_Static.SetCVal_s('write.step.unit', 'MM')
                    for shape in exact:
                        if writer.Transfer(shape, STEPControl_StepModelType.STEPControl_AsIs) != IFSelect_ReturnStatus.IFSelect_RetDone:
                            raise ConversionError('STEP geometry transfer failed.')
                    if writer.Write(str(temp)) != IFSelect_ReturnStatus.IFSelect_RetDone:
                        raise ConversionError('STEP write failed.')
                elif fmt == 'iges':
                    writer = IGESControl_Writer('MM', 0)
                    for shape in exact:
                        if not writer.AddShape(shape):
                            raise ConversionError('IGES geometry transfer failed.')
                    writer.ComputeModel()
                    if not writer.Write(str(temp)):
                        raise ConversionError('IGES write failed.')
                else:
                    if not BRepTools.Write_s(geometry.make_compound(exact), str(temp)):
                        raise ConversionError('BREP write failed.')
            else:
                if mesh_data is None:
                    mesh_data = triangles(named, deviation)
                    if mesh_data[3]:
                        report['warnings'].append('Mesh exports omit curves/points: ' + ', '.join(mesh_data[3]))
                write_mesh(temp, fmt, mesh_data)
            if not temp.exists() or temp.stat().st_size == 0:
                raise ConversionError('The exporter did not create a nonempty output file.')
            temp.replace(final)
            report['outputs'].append({'format': fmt, 'path': str(final), 'bytes': final.stat().st_size})
        except Exception as exc:
            temp.unlink(missing_ok=True)
            report['format_errors'][fmt] = str(exc)
    report['status'] = ('partial' if report['skipped_objects'] else 'complete') if not report['format_errors'] else ('partial' if report['outputs'] else 'failed')
    report['folder'] = str(run)
    (run/'conversion-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    progress(1, 'Complete' if report['outputs'] else 'No formats could be exported')
    return report


def write_progress(state_path, value, message):
    """Best-effort progress: Windows readers can briefly prevent replacement."""
    temporary = state_path.with_suffix('.tmp')
    payload = json.dumps({'progress': value, 'message': message})
    for attempt in range(4):
        try:
            temporary.write_text(payload, encoding='utf-8')
            os.replace(temporary, state_path)
            return True
        except PermissionError:
            if attempt < 3:
                time.sleep(0.01 * (attempt + 1))
        except OSError:
            break
    # Status is advisory. Export and result/report failures still propagate.
    try:
        temporary.unlink(missing_ok=True)
    except OSError:
        pass
    return False


def worker(job_path):
    job_path = Path(job_path)
    job = json.loads(job_path.read_text(encoding='utf-8'))
    state_path = job_path.with_suffix('.state.json')
    def update(value, text):
        write_progress(state_path, value, text)
    try:
        result = convert(job['source'], job['destination'], job['formats'], job['options'], update)
    except ConversionReview as exc:
        result = {'status': 'needs_confirmation', 'needs_confirmation': True,
                  'error': str(exc), 'skipped_objects': exc.issues, 'outputs': []}
    except Exception as exc:
        result = {'status': 'failed', 'error': str(exc), 'traceback': traceback.format_exc(), 'outputs': []}
    job_path.with_suffix('.result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')

