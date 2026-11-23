from contextlib import nullcontext
import ctypes
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from PIL import Image
import pytest

import run_ocufield
from ocufield import experiment, private_desktop, ui
from ocufield.storage import validate_config


@pytest.fixture
def graphics(monkeypatch):
    events = []
    frame = []
    info = {1: b'Microsoft Corporation', 2: b'GDI Generic', 3: b'1.1.0'}

    def prepare(image, resources):
        resources.callback(events.append, 'texture closed')
        return lambda: frame.append(image)

    def read(x, y, w, h, fmt, kind, pixels):
        events.append('read pixels')
        image = frame[-1].transpose(Image.Transpose.FLIP_TOP_BOTTOM).convert('RGB')
        data = image.tobytes()
        ctypes.memmove(pixels, data, len(data))

    def clear(mask):
        assert mask == gl.GL_COLOR_BUFFER_BIT
        frame.clear()
        events.append('clear')

    def flip():
        events.append('flip')
        assert not frame
        raise experiment.Aborted

    gl = SimpleNamespace(
        GLubyte=ctypes.c_ubyte, GL_VENDOR=1, GL_RENDERER=2, GL_VERSION=3, GL_BACK=4,
        GL_RGB=5, GL_UNSIGNED_BYTE=6, GL_PACK_ALIGNMENT=7, GL_CLIENT_PIXEL_STORE_BIT=8,
        GL_COLOR_BUFFER_BIT=9, GL_NO_ERROR=0,
        glGetString=info.get, glReadPixels=read, glClear=clear, glGetError=lambda: 0,
        glDrawBuffer=lambda target: events.append(('draw buffer', target)),
        glReadBuffer=lambda target: events.append(('read buffer', target)),
        glPushClientAttrib=lambda _: None, glPopClientAttrib=lambda: None, glPixelStorei=lambda *_: None,
    )
    window = SimpleNamespace(_hw_handle=123, flip=flip, close=lambda: events.append('window closed'))
    visual = SimpleNamespace(Window=lambda **_: window)
    display = SimpleNamespace(
        size=(5, 4), prepare=prepare, initial_refresh=lambda _: window.flip(),
        close=lambda: events.append('display closed'),
    )
    monkeypatch.setitem(sys.modules, 'pyglet', SimpleNamespace(gl=gl))
    monkeypatch.setattr(experiment, 'Display', lambda *_: display)
    monkeypatch.setattr(experiment, 'HiddenSelfTestDisplay', lambda *_: display)
    monkeypatch.setattr(experiment, 'monitor_refresh_hz', lambda _: 60)
    monkeypatch.setattr(experiment, 'trial', lambda *_: pytest.fail('Trial started before the graphics check'))
    return SimpleNamespace(gl=gl, info=info, visual=visual, display=display, events=events)


@pytest.mark.parametrize('mode', ['formal', 'practice'])
def test_real_run_reads_and_clears_only_the_back_buffer_before_first_flip(graphics, mode):
    config = validate_config(dict(selectedMode=mode))
    with pytest.raises(experiment.Aborted):
        experiment.run_experiment(graphics.visual, config, fullscreen=False)
    assert graphics.events == [
        ('draw buffer', graphics.gl.GL_BACK), ('read buffer', graphics.gl.GL_BACK),
        'read pixels', 'texture closed', 'clear', 'flip', 'display closed', 'window closed',
    ]


def bad_readback(*args):
    pixels = args[-1]
    ctypes.memset(pixels, 255, len(pixels))


@pytest.mark.parametrize('stale_count', [1, 31])
def test_graphics_check_drains_stale_errors(graphics, stale_count):
    no_error = graphics.gl.GL_NO_ERROR
    flags = iter([1282] * stale_count + [no_error, no_error])
    graphics.gl.glGetError = lambda: next(flags)

    experiment.verify_pixels(graphics.display)

    assert next(flags, None) is None
    assert graphics.events[-1] == 'clear'


def test_graphics_check_stops_after_32_pending_errors(graphics):
    flags = iter([1282] * 32 + [graphics.gl.GL_NO_ERROR])
    graphics.gl.glGetError = lambda: next(flags)

    with pytest.raises(experiment.GraphicsCheckError, match=r'^GRAPHICS_CHECK_FAILED'):
        experiment.verify_pixels(graphics.display)

    assert next(flags) == graphics.gl.GL_NO_ERROR
    assert not graphics.events


@pytest.mark.parametrize('failure', ['mismatch', 'missing', 'query exception', 'read exception', 'GL error'])
def test_graphics_check_fails_closed(graphics, failure):
    def raise_gl(*_):
        raise OSError('GL call failed')

    if failure == 'mismatch':
        graphics.gl.glReadPixels = bad_readback
    elif failure == 'missing':
        graphics.info[graphics.gl.GL_VENDOR] = ctypes.POINTER(ctypes.c_ubyte)()
    elif failure == 'query exception':
        graphics.gl.glGetString = lambda parameter: (
            raise_gl() if parameter == graphics.gl.GL_VENDOR else graphics.info[parameter]
        )
    elif failure == 'read exception':
        graphics.gl.glReadPixels = raise_gl
    else:
        graphics.gl.glGetError = lambda: 1282 if 'read pixels' in graphics.events else graphics.gl.GL_NO_ERROR

    with pytest.raises(experiment.GraphicsCheckError, match=r'^GRAPHICS_CHECK_FAILED .*未產生資料') as error:
        experiment.verify_pixels(graphics.display)
    assert 'GL_RENDERER=GDI Generic / GL_VERSION=1.1.0' in str(error.value)
    vendor = '無法讀取' if failure in ('missing', 'query exception') else 'Microsoft Corporation'
    assert f'GL_VENDOR={vendor}' in str(error.value)
    if failure not in ('missing', 'query exception'):
        assert graphics.events[-1] == 'clear'


def test_graphics_failure_restores_settings_without_result_or_export(graphics, monkeypatch):
    graphics.gl.glReadPixels = bad_readback
    app = ui.App.__new__(ui.App)
    app.visual = graphics.visual
    app.config = validate_config({})
    app.subject = 'SUBJ_TEST01'
    app.result = object()
    seen = []
    messages = []
    app.root = SimpleNamespace(
        winfo_id=lambda: 123, withdraw=lambda: seen.append('hidden'),
        update_idletasks=lambda: None, deiconify=lambda: seen.append('visible'),
    )
    app.settings = lambda: seen.append('settings')
    app.results = app.save_csv = app.save_json = lambda: pytest.fail('A graphics failure produced a result or export')
    monkeypatch.setattr(ui, 'monitor_rect', lambda _: None)
    monkeypatch.setattr(ui.messagebox, 'showerror', lambda title, message, **_: messages.append(message))

    app.start()

    assert app.result is None and seen == ['hidden', 'visible', 'visible', 'settings']
    assert len(messages) == 1 and messages[0].startswith('GRAPHICS_CHECK_FAILED ')
    assert 'flip' not in graphics.events
    assert graphics.events[-3:] == ['clear', 'display closed', 'window closed']


def test_hidden_selftest_graphics_failure_writes_only_error(graphics, monkeypatch):
    graphics.gl.glReadPixels = bad_readback
    monkeypatch.setattr(experiment, 'runtime', lambda _: nullcontext(graphics.visual))
    monkeypatch.setattr(run_ocufield, 'enable_per_monitor_dpi', lambda: None)
    monkeypatch.setattr(sys, 'addaudithook', lambda _: None)
    monkeypatch.setattr(private_desktop, 'require_private_desktop', lambda _: None)
    monkeypatch.setenv(private_desktop.DESKTOP_ENV, 'TestDesktop')
    with TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
        output = Path(directory)
        (output / 'selftest.json').write_text('{}', encoding='utf-8')
        monkeypatch.setattr(sys, 'argv', ['run_ocufield.py', '--self-test', str(output)])

        assert run_ocufield.main() == 1
        assert {path.name for path in output.iterdir()} == {'selftest-error.txt'}
        message = (output / 'selftest-error.txt').read_text(encoding='utf-8')
        assert 'GRAPHICS_CHECK_FAILED ' in message and 'GDI Generic' in message
