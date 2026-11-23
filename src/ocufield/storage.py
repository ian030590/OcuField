import ctypes
from ctypes import wintypes
import json
from math import isfinite
import os
from pathlib import Path
from secrets import choice
from string import ascii_uppercase, digits
from tempfile import NamedTemporaryFile
import uuid

from .logic import AXES

DEFAULTS = dict(
    selectedSubtest=1, selectedMode='formal', stopConditionType='adaptive_80',
    selectedTrialCount=48, selectedAxes=list(AXES), screenWidthCm=53.1,
    screenHeightCm=29.9, viewingDistanceCm=50, targetVisualAngleDeg=15.0,
    vehicleVisualAngleDeg=2.5, contrastPercent=100,
)
RANGES = dict(
    screenWidthCm=(10, 300), screenHeightCm=(10, 300), viewingDistanceCm=(10, 300),
    targetVisualAngleDeg=(5, 35), vehicleVisualAngleDeg=(0.8, 5), contrastPercent=(5, 100),
)


def new_subject_id():
    return 'SUBJ_' + ''.join(choice(ascii_uppercase + digits) for _ in range(6))


def config_path():
    return Path(os.environ['APPDATA']) / 'OcuField' / 'config.json'


def validate_config(data):
    config = dict(DEFAULTS, selectedAxes=list(AXES))
    if not isinstance(data, dict):
        return config
    for key, options in (
        ('selectedSubtest', (1, 2, 3)),
        ('selectedMode', ('formal', 'practice', 'instruction')),
        ('stopConditionType', ('adaptive_80', 'fixed_trials')),
    ):
        if type(data.get(key)) is not bool and data.get(key) in options:
            config[key] = data[key]
    config['selectedSubtest'] = int(config['selectedSubtest'])
    count = data.get('selectedTrialCount')
    if type(count) in (float, int) and isfinite(count) and count > 0:
        config['selectedTrialCount'] = count
    axes = data.get('selectedAxes')
    if isinstance(axes, list):
        valid = [axis for axis in axes if type(axis) in (float, int) and 0 <= axis <= 7]
        if valid:
            config['selectedAxes'] = valid
    for key, (minimum, maximum) in RANGES.items():
        value = data.get(key)
        if type(value) in (float, int) and minimum <= value <= maximum:
            config[key] = value
    return config


def load_config():
    try:
        return validate_config(json.loads(config_path().read_text(encoding='utf-8')))
    except FileNotFoundError:
        return validate_config({})


def save_config(config):
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    content = {key: config[key] for key in DEFAULTS}
    write_file(path, json.dumps(content, ensure_ascii=False, indent=2).encode('utf-8'))


def write_file(path, content, *, replace=True):
    with NamedTemporaryFile(dir=path.parent, delete=False) as file:
        pending = Path(file.name)
        try:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
            file.close()
            if replace:
                pending.replace(path)
            else:
                try:
                    pending.rename(path)
                except FileExistsError:
                    if path.read_bytes() != content:
                        raise
        finally:
            file.close()
            pending.unlink(missing_ok=True)


def downloads_path():
    guid = (ctypes.c_ubyte * 16).from_buffer_copy(
        uuid.UUID('374de290-123f-4565-9164-39c4925e467b').bytes_le
    )
    result = ctypes.c_wchar_p()
    known_folder = ctypes.windll.shell32.SHGetKnownFolderPath
    known_folder.argtypes = (ctypes.c_void_p, wintypes.DWORD, wintypes.HANDLE, ctypes.POINTER(ctypes.c_wchar_p))
    known_folder.restype = ctypes.c_long
    try:
        status = known_folder(ctypes.byref(guid), 0, None, ctypes.byref(result))
        if status < 0:
            raise OSError(f'無法取得下載資料夾 (0x{status & 0xffffffff:08X})')
        return Path(result.value)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(result)


def monitor_rect(hwnd):
    class MonitorInfo(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('monitor', wintypes.RECT),
                    ('work', wintypes.RECT), ('flags', wintypes.DWORD)]

    user32 = ctypes.windll.user32
    user32.MonitorFromWindow.argtypes = (wintypes.HWND, wintypes.DWORD)
    user32.MonitorFromWindow.restype = wintypes.HMONITOR
    user32.GetMonitorInfoW.argtypes = (wintypes.HMONITOR, ctypes.POINTER(MonitorInfo))
    info = MonitorInfo(ctypes.sizeof(MonitorInfo))
    if not user32.GetMonitorInfoW(user32.MonitorFromWindow(hwnd, 2), ctypes.byref(info)):
        raise OSError('無法取得螢幕的實體像素尺寸')
    rect = info.monitor
    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top


def monitor_refresh_hz(hwnd):
    import win32api
    import win32con

    try:
        monitor = win32api.MonitorFromWindow(hwnd, win32con.MONITOR_DEFAULTTONEAREST)
        device = win32api.GetMonitorInfo(monitor)['Device']
        frequency = win32api.EnumDisplaySettings(device, win32con.ENUM_CURRENT_SETTINGS).DisplayFrequency
    except win32api.error as error:
        raise RuntimeError('無法取得目前螢幕的標稱更新率。') from error
    if frequency <= 1:
        raise RuntimeError('無法取得目前螢幕的標稱更新率。')
    return frequency
