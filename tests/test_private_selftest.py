from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import run_ocufield
from ocufield import private_desktop
from ocufield.experiment import Display, HiddenSelfTestDisplay


def test_default_selftest_relaunches_before_gui_setup(monkeypatch):
    def prevent_gui():
        raise AssertionError('Parent reached GUI setup')

    commands = []
    monkeypatch.delenv(private_desktop.DESKTOP_ENV, raising=False)
    monkeypatch.setattr(run_ocufield, 'enable_per_monitor_dpi', prevent_gui)
    monkeypatch.setattr(sys, 'addaudithook', lambda _: None)

    def launch(command):
        commands.append(command)
        return 37

    monkeypatch.setattr(private_desktop, 'run_on_private_desktop', launch)
    with TemporaryDirectory(prefix='self test ', dir=Path(__file__).resolve().parents[1]) as root:
        output = Path(root) / 'hidden results'
        monkeypatch.setattr(sys, 'argv', ['run_ocufield.py', '--self-test', str(output)])
        assert run_ocufield.main() == 37
        assert commands == [[sys.executable, str(Path(run_ocufield.__file__)), '--self-test', str(output)]]
        assert '37' in (output / 'selftest-error.txt').read_text(encoding='utf-8')


def test_child_on_wrong_desktop_exits_before_gui_setup(monkeypatch):
    reached_gui = []
    monkeypatch.setattr(run_ocufield, 'enable_per_monitor_dpi', lambda: reached_gui.append(True))
    monkeypatch.setattr(sys, 'addaudithook', lambda _: None)
    monkeypatch.setenv(private_desktop.DESKTOP_ENV, 'WrongDesktop')
    with TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as root:
        monkeypatch.setattr(sys, 'argv', ['run_ocufield.py', '--self-test', root])
        assert run_ocufield.main() == 1
        assert not reached_gui
        assert 'did not start on its private Windows desktop' in (Path(root) / 'selftest-error.txt').read_text(encoding='utf-8')


def test_hidden_selftest_flips_render_with_simulated_timestamps(monkeypatch):
    native_flips = []
    vsync = []
    monkeypatch.setattr(Display, '__init__', lambda self, *_: setattr(self, 'handle', SimpleNamespace(set_vsync=vsync.append)))
    monkeypatch.setattr(Display, 'flip', lambda _: native_flips.append(True) or 100)
    display = HiddenSelfTestDisplay(None, False)
    assert [display.flip() for _ in range(3)] == [1 / 60, 2 / 60, 3 / 60]
    assert display.clock() == 3 / 60 and len(native_flips) == 3
    assert vsync == [False]
