from pathlib import Path
import importlib.util

psychopy = Path(importlib.util.find_spec('psychopy').origin).parent
data = [
    ('LICENSE', '.'),
    (str(psychopy / 'preferences' / 'Windows.spec'), 'psychopy/preferences'),
    (str(psychopy / 'app' / 'appData.spec'), 'psychopy/app'),
    (str(psychopy / 'LICENSE.txt'), 'psychopy'),
    (str(psychopy / 'LICENSES.txt'), 'psychopy'),
]

analysis = Analysis(
    ['run_ocufield.py'],
    pathex=['src'],
    datas=data,
    hiddenimports=['psychopy.visual.backends.pygletbackend', 'pyglet.canvas.win32',
                   'pyglet.window.win32', 'pyglet.gl.win32'],
    excludes=['pytest', 'IPython', 'notebook', 'pyglet.media', 'psychopy.app', 'psychopy.demos',
              'psychopy.experiment', 'psychopy.iohub', 'psychopy.sound', 'psychopy.tests'],
    hooksconfig={'matplotlib': {'backends': ['Agg']}},
)
psychopy_data = {Path(destination) / Path(source).name for source, destination in data}
analysis.datas = [
    item for item in analysis.datas
    if Path(item[0]).parts[0] != 'psychopy'
    or Path(item[0]) in psychopy_data
    or Path(item[0]).parts[1] in {'localization', 'tools', 'visual'}
    or Path(item[0]).name == 'psychopy.ico'
]
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz, analysis.scripts, analysis.binaries, analysis.datas, [],
    name='OcuField', console=False, upx=False,
)
