RHINO CONVERTER — offline Windows / Mac prototype

This app converts Rhino .3dm files without installing or launching Rhino.
There is no website, server, account, subscription, or conversion API.
It uses rhino3dm / openNURBS to read files and Open Cascade for CAD export.
Optional signed updates download release metadata/packages from GitHub;
models and their filenames are never uploaded. Conversion remains offline.

WHAT IS IN THIS DOWNLOAD
This is the source-and-build package, not a prebuilt Windows EXE or Mac app.
The conversion engine has been tested on Linux. Windows and Mac execution
and PyInstaller packaging still need testing on the respective computers.

EASY OFFICE INSTALLERS
Windows: double-click Build-Installer-Windows.bat, then share only
dist\RhinoConverter-Setup.exe. Coworkers double-click it and click Install.
The installer bundles the engine, creates desktop and Start menu shortcuts,
and adds an uninstaller in Windows Settings. It installs for the current user.
Mac: double-click Build-Installer-Mac.command, then share the resulting
dist/RhinoConverter-Mac-arm64.dmg or RhinoConverter-Mac-x86_64.dmg.
Coworkers drag the app into Applications. See INSTALLATION.txt for details.
Build and test the native installer once before sharing it with the office.

BUILD ONCE, SHARE THE APP
1. On ONE Windows 10/11 64-bit build computer, install Python 3.12 from:
   https://www.python.org/downloads/windows/
2. Extract this entire source ZIP into a folder.
3. Double-click Build-Windows.bat. Internet is needed for this one-time build
   to download the open-source engine and packaging tools.
4. Open dist\RhinoConverter\RhinoConverter.exe and test office sample files.
5. Send dist\RhinoConverter-Windows.zip to coworkers. They extract it and
   run RhinoConverter.exe. They do not install Rhino, Python, or FreeCAD.
   Keep the full folder together; the EXE depends on its _internal folder.
   The folder can be copied to another computer or USB drive.

BUILD ON A MAC
1. Use macOS 14 or newer. The pinned rhino3dm 8.35.0 Python 3.12 wheel
   requires this version. Both Intel and Apple Silicon engine wheels exist.
2. Install Python 3.12 from https://www.python.org/downloads/macos/
3. Extract this source ZIP, then double-click Build-Mac.command.
   If it is not executable, open Terminal in this folder and run:
   bash Build-Mac.command
4. Test dist/RhinoConverter.app with your office models.
5. Share dist/RhinoConverter-Mac-arm64.zip with Apple Silicon Macs, or
   dist/RhinoConverter-Mac-x86_64.zip with Intel Macs. Build separately with
   native Python on each architecture; this is not a universal app build.
   Coworkers extract the ZIP and open the app without Rhino or Python.
The initial build needs internet to install dependencies. Conversion is offline.
The script creates an ad-hoc signed development app; Developer ID signing and
notarization are needed for normal distribution without macOS security prompts.
Use Add files on Mac; Finder drag-and-drop is not implemented in this version.

USING THE APP
A short Preparing converter screen appears while the interface is sized.
The main window uses separate cards for files, formats and output settings.
Wide windows use two columns; smaller windows stack the cards. Selected
format cards are highlighted, and a result summary accompanies conversion details.
On Windows, drag one or more .3dm files from Explorer into the app. On either
platform, use Add files. Select formats, destination, optionally an output name,
then Convert. For one source, the chosen name is used for its folder and files.
Export filenames include the type: Office fixture_STEP.step,
Office fixture_STL.stl, etc. Leave the output name blank to use the source name.
For a batch, source filenames are appended to the chosen name.
Each source gets its own named folder; existing folders get a (2), (3), etc.
suffix. Previous exports are never overwritten.
Each conversion works from a temporary copy; the source file is untouched.
A JSON report accompanies completed exports.
Dimensions, text, annotation objects, hatches and viewport references are
skipped automatically. Construction curves are skipped by default; uncheck
Skip curves if you need to include them.
If other objects cannot be converted, the app pauses and lists them. Choose
Convert anyway to export convertible geometry, Skip this file to continue the
batch, or Stop. A partial export report lists every skipped object.
The layout wraps into fewer columns when resized and scrolls when needed.
Conversion buttons and progress remain visible at the bottom.
Stop cancels the active worker and remaining batch files. Completed exports
stay on disk. An incomplete output may remain as partial.* after an abrupt
worker crash or cancellation; do not use that file.

FORMAT SUPPORT IN THIS VERSION
STEP (.step): BRep/NURBS CAD geometry, including valid reconstructed solids.
IGES (.iges): CAD surfaces and curves; receiving applications may see shells.
BREP (.brep): Open Cascade boundary representation.
STL (.stl), OBJ (.obj), PLY (.ply): triangulated geometry.
All coordinates are converted to millimetres. STL, OBJ and PLY do not reliably
carry a unit system; set import units to millimetres in the receiving app.
The mesh detail control sets requested tessellation deviation in millimetres.

This is not an every-format converter. DWG, SAT, Parasolid (.x_t/.x_b),
native SolidWorks, Inventor, CATIA and Revit output are not implemented.
No menu items pretend to export those formats.

GEOMETRY AND LIMITS
The reader supports curves, NURBS surfaces, Breps, extrusions, triangle
meshes and placed block members. Blocks are flattened; editable assembly
structure, layers, materials, textures, lights, named views, annotations,
parametric history and plug-in data are not preserved in the output.
Annotations/lights are reported as omissions. Unsupported geometry such
as SubD or point clouds prompts for Convert anyway instead of disappearing.
Hidden objects and hidden layers are excluded unless the checkbox is enabled.
Construction curves are skipped unless explicitly included. Mesh output cannot
represent curves or points; those omissions are recorded in the report.
A file containing mesh objects will not export to STEP/IGES/BREP: the app
does not disguise faceted meshes as exact CAD surfaces or silently drop them.
Unitless and custom-unit files are rejected. Assign a standard unit first.

CAD reconstruction is experimental and trimming boundaries may be approximated.
The circular trim test measured a 0.004% surface-area error; this is not a
universal tolerance guarantee. The app checks reconstructed validity,
Brep face count, mesh fallback, and closed-solid status, but these checks do
not prove that every trim, tolerance, hole or detail matches the source.
Check dimensions and geometry in the receiving CAD system before manufacture.
STEP output carries geometry but does not preserve Rhino object names/colors.
Each worker has a ten minute limit; a crash is isolated from the app.
There is no 3D preview in this first version.

DEVELOPMENT
Python 3.12, requirements.txt, and app.py run the source version.
python -m unittest discover -s tests -v
The worker can be invoked as: python app.py --worker job.json
See engine.py for the job schema and conversion report format.

UPDATING WITHOUT REBUILDING
On a computer where the build has already installed Python and dependencies:
1. Close the converter.
2. Extract a new source ZIP over this same rhino-converter folder and choose
   Replace for updated files. Keep the existing .venv folder.
3. Double-click Run-Source.bat. This launches the current Python files directly.
No EXE rebuild is needed for source-mode code changes. Dependencies may need
updating if requirements.txt changes. The existing EXE still contains the old
code; Build-Windows.bat must be rerun to update that packaged version.
On a Mac, use Run-Source-Mac.command after replacing the updated source
files, keeping .venv. Rebuild with Build-Mac.command to update a packaged app.
Explorer drag-and-drop uses the Windows shell directly; no new dependencies
are needed for this update. The native Explorer event hook still needs manual
testing on Windows. Other operating systems can use Add files.
SIGNED GITHUB UPDATES
Version 0.5.0 adds startup checks and an Updates menu with verified downloads
and installation. See GITHUB-UPDATES.txt for the one-time repository/signing
setup. Unconfigured builds do not fetch or install releases. Future GitHub
releases must carry metadata signed with the matching private key.
Configure-Updates.bat also migrates the build environment to the OCP engine
without VTK. For this dependency change, run it or rebuild before source use.
GitHub Actions can build Windows and Mac releases from matching version tags.
Security checks, dependency findings and limits are documented in SECURITY.txt.

Sources / acknowledgments:
https://github.com/chisomobanzi/Serpentine3D
https://github.com/mcneel/rhino3dm
https://github.com/CadQuery/OCP
https://dev.opencascade.org/
Mac dependency platform requirements:
https://pypi.org/project/rhino3dm/8.35.0/
https://pypi.org/project/cadquery-ocp-novtk/7.8.1.1.post1/
