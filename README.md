# Rhino Converter

Convert Rhino `.3dm` files locally without installing Rhino or Python. Supports STEP, IGES, BREP, STL, OBJ and PLY.

## Download and install

Download installers from [GitHub Releases](https://github.com/ljmcglinch/rhino-converter/releases/latest).

- **Windows 10/11, 64-bit:** run `RhinoConverter-Setup.exe`.
- **Mac, macOS 14 or newer:** choose the disk image for Apple Silicon (`arm64`) or Intel (`x86_64`), open it and drag the app into Applications.

Windows installers currently have no Authenticode signature. Mac packages currently use development signatures and have not been notarized. Native Mac installation and replacement still require testing.

Original files stay unchanged. Annotations and curves are skipped by default. Review converted production geometry before relying on it.

## Where converted files go

Both **Create new folder** and **Use source folder** are checked by default.

| Create new folder | Use source folder | Result |
| --- | --- | --- |
| Checked | Checked | A new folder beside each source file. |
| Unchecked | Checked | Files directly beside each source file. |
| Checked | Unchecked | Choose a destination; create a new folder there for each source. |
| Unchecked | Unchecked | Choose a destination; save files directly into it. |

New folders use the source filename, or the optional output name. For batches, each file uses its own source folder when that option is checked. Existing folders, exports and reports are preserved by adding a numbered suffix when needed. Direct exports get a report named after the output, such as `Fixture_conversion-report.json`.

## Updates and privacy

Conversion happens on your computer. No ChatGPT account, API key or GitHub token is required. Update checks contact GitHub; CAD files are never uploaded by the converter.

Configured builds verify release metadata with a pinned public key, then verify each download's size and SHA-256 hash before installation. Failed checks do not prevent conversion. Older installations showing **Updates not configured** need the first configured installer once.

Only the public verification key belongs in this repository. The private update signing key must stay outside the project and in the protected GitHub Actions `release` environment. It is separate from any API key.

## Build and verify

Use native Python 3.12 and the supplied build scripts. Run `Build-Installer-Windows.bat` on Windows or `Build-Installer-Mac.command` on a Mac. These install pinned dependencies, audit build dependencies and run tests before packaging. Mac builds are separate for Apple Silicon and Intel.

GitHub Actions checks source changes on all three platforms. Matching version tags build installers; publication waits for all builds and approval of the protected release environment.

See [installation checks](INSTALLATION.txt), [update setup](GITHUB-UPDATES.txt), [security notes](SECURITY.txt) and [third-party notices](THIRD-PARTY-NOTICES.txt).
