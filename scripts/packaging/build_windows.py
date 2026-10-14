"""Build a clean onedir Windows release; never collect the working library."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

VERSION = '0.1.0'
FFMPEG_SHA256 = 'fb2de01912edb449a5eba1cc487696c7f71ebb7b325e5c5c69434642ec2ba6b0'
ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ffmpeg-archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='A new, empty build directory')
    args = parser.parse_args()
    if sys.platform != 'win32' or sys.maxsize <= 2**32:
        raise RuntimeError('Build on Windows x64 with a 64-bit Python environment')
    archive = args.ffmpeg_archive.resolve()
    if hashlib.sha256(archive.read_bytes()).hexdigest() != FFMPEG_SHA256:
        raise RuntimeError('FFmpeg archive differs from the pinned upstream release')
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=False)
    vendor = output/'ffmpeg'; vendor.mkdir()
    with tarfile.open(archive) as tar:
        tar.extractall(vendor, filter='data')
    ffmpeg = subprocess.check_output([str(vendor/'ffmpeg.exe'), '-version'], text=True)
    if any(flag in ffmpeg for flag in ('--enable-gpl', '--enable-nonfree', '--enable-version3')):
        raise RuntimeError('Unexpected FFmpeg license configuration')
    data = [(ROOT/'data/meta', 'data/meta'), (vendor, 'vendor/ffmpeg'),
            (ROOT/'scripts/common/source_catalog/character_export.jsfl', 'source_catalog')]
    # Optional AI workers run in a separately configured Python; include their sources.
    for folder in ('scripts/common', 'scripts/ai'):
        for path in (ROOT/folder).rglob('*'):
            if path.suffix in {'.py', '.jsfl'}:
                data.append((path, path.parent.relative_to(ROOT).as_posix()))
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
               '--windowed', '--noupx', '--name', 'PonyPoseSearch',
               '--additional-hooks-dir', str(ROOT/'scripts/packaging/hooks'),
               '--distpath', str(output/'dist'), '--workpath', str(output/'work'),
               '--specpath', str(output), '--paths', str(ROOT/'scripts/common'),
               '--paths', str(ROOT/'scripts/m10'), '--paths', str(ROOT/'scripts/packaging')]
    for package in ('multispecies', 'source_catalog', 'workflow'):
        command += ['--collect-submodules', package]
    for source, target in data:
        command += ['--add-data', str(source)+';'+target]
    command += [str(ROOT/'scripts/packaging/entry.py')]
    subprocess.run(command, check=True, cwd=ROOT)
    app = output/'dist/PonyPoseSearch'
    licenses = app/'licenses'; licenses.mkdir()
    shutil.copy2(Path(sys.base_prefix)/'LICENSE.txt', licenses/'Python.txt')
    shutil.copy2(Path(sys.base_prefix)/'tcl/tk8.6/license.terms', licenses/'Tk.txt')
    shutil.copy2(ROOT/'scripts/packaging/licenses/Tcl.txt', licenses/'Tcl.txt')
    shutil.copy2(ROOT/'scripts/packaging/licenses/GCC-RUNTIME-LIBRARY-EXCEPTION.txt',
                 app/'_internal/vendor/ffmpeg/GCC-RUNTIME-LIBRARY-EXCEPTION.txt')
    for name in ('Pillow', 'pyinstaller'):
        dist = importlib.metadata.distribution(name)
        for file in dist.files or []:
            if 'license' in str(file).lower() or 'copying' in str(file).lower():
                path = Path(dist.locate_file(file))
                if path.is_file():
                    shutil.copy2(path, licenses/(name+'-'+path.name))
    shutil.copy2(ROOT/'docs/windows-release-notices.md', app/'第三方组件说明.md')
    shutil.copy2(ROOT/'docs/windows-quickstart.txt', app/'开始使用.txt')
    (app/'VERSION.txt').write_text(VERSION+'\n', encoding='utf-8')
    manifest = {'version': VERSION, 'python': sys.version, 'ffmpeg': ffmpeg,
                'ffmpeg_archive_sha256': FFMPEG_SHA256,
                'packages': {n: importlib.metadata.version(n) for n in ('PyInstaller', 'Pillow', 'pyinstaller-hooks-contrib')}}
    (app/'build-info.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    # The bundle is fully created before making its only distributable ZIP.
    name = f'PonyPoseSearch-{VERSION}-Windows-x64'
    zipped = shutil.make_archive(str(output/name), 'zip', app.parent, app.name)
    digest = hashlib.sha256(Path(zipped).read_bytes()).hexdigest()
    (output/'SHA256SUMS.txt').write_text(digest+'  '+Path(zipped).name+'\n', encoding='utf-8')
    print(json.dumps({'zip': zipped, 'sha256': digest, 'bytes': Path(zipped).stat().st_size}))


if __name__ == '__main__':
    main()
