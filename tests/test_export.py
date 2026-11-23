import codecs
import csv
from datetime import datetime
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from ocufield.export import json_data, write_csvs
from ocufield.logic import calculate_screen_geometry
from ocufield.storage import validate_config

WHEN = datetime(2026, 2, 3, 4, 5, 6)
RAW_HEADER = (
    '受試者代號,測驗日期,測驗時間,Subtest項目代碼,Subtest項目名稱,題次序號,題次類型,設定呈現時間 (ms),'
    '實際呈現時間 (ms),呈現影格數,遺失影格數,螢幕更新率 (Hz),對比度 (%),車輛大小視角 (度),周邊偏心視角 (度),'
    '中央目標種類,中央作答選擇,中央作答正確,周邊目標方位代碼,周邊目標方位名稱,周邊作答選擇代碼,周邊作答選擇名稱,'
    '周邊作答正確,本題整體判定,作答反應時間 (ms),滑鼠軌跡取樣數,滑鼠軌跡數據 (JSON)'
)
STAT_HEADER = '參數項目,參數代碼,設定數值,單位,詳細說明'


@pytest.mark.parametrize(('subtest', 'mode', 'pixels', 'actual', 'clamped'), [
    (1, 'practice', (1920, 1080), '14.73', 'TRUE'),
    (3, 'formal', (2880, 1920), '15.00', 'FALSE'),
])
def test_csv_format(subtest, mode, pixels, actual, clamped):
    config, result = sample(subtest, mode, pixels)
    with TemporaryDirectory(prefix='csv-test-', dir=Path(__file__).resolve().parents[1]) as tmp:
        raw, stats = write_csvs(Path(tmp), config, result, WHEN)
        assert [path.name for path in (raw, stats)] == [
            f'20260203-040506-Subtest{subtest}-原始分數.csv', f'20260203-040506-Subtest{subtest}-統計成績.csv',
        ]
        raw_data, stat_data = raw.read_bytes(), stats.read_bytes()
        raw_header, _, _ = raw_data.partition(b'\r\n')
        assert raw_header == codecs.BOM_UTF8 + (RAW_HEADER + ',實際周邊偏心視角 (度)').encode()
        assert stat_data.startswith(codecs.BOM_UTF8 + f'{STAT_HEADER}\r\n'.encode())
        for data in (raw_data, stat_data):
            assert b'\n' not in data.replace(b'\r\n', b'')
            assert not data.endswith(b'\r\n')

        _, actual_stat, clamp_stat = stat_data.rsplit(b'\r\n', 2)
        assert '"subtest_code","Subtest {}","-","周邊視野測驗核心項目"'.format(subtest).encode() in stat_data
        assert actual_stat.decode() == (
            f'"實際周邊偏心視角","actual_target_visual_angle_deg","{actual}","deg (度 / °)",'
            '"依測驗畫面像素尺寸換算的周邊目標刺激物偏心視角"'
        )
        assert clamp_stat.decode() == (
            f'"周邊偏心視角受限","eccentricity_clamped","{clamped}","-","設定視角與實際視角相差超過 0.005 度"'
        )

        raw_rows = list(csv.reader(io.StringIO(raw_data.decode('utf-8-sig'))))
        assert [row[-1] for row in raw_rows[1:]] == [actual + '°'] * len(result['trials'])
        row = raw_rows[1]
        assert row[0] == '編號,"A"\r\nB'
        assert row[7:12] == ['50.01', '50.5', '6', '0', '120']
        assert row[18] == ('0' if subtest == 3 else 'N/A')
        assert json.loads(row[-2]) == [{'x': 4, 'y': 8, 't': 1}]
        assert write_csvs(Path(tmp), config, result, WHEN) == (raw, stats)
        with pytest.raises(FileExistsError):
            write_csvs(Path(tmp), dict(config, subjectId='DIFFERENT'), result, WHEN)


def test_json_export_keys():
    config, result = sample(1, 'practice')
    exported = json_data(config, result, WHEN)
    assert tuple(exported) == (
        'experiment', 'version', 'date_time', 'subjectId', 'subtestId', 'contrast',
        'targetVisualAngle', 'vehicleVisualAngle', 'final_rt', 'refreshHz', 'refreshMs',
        'timing_invalid_repeats', 'timing_stopped', 'trials', 'actualTargetVisualAngle', 'eccentricityClamped',
    )
    row = exported['trials'][0]
    assert tuple(row) == (
        'subjectId', 'date_time', 'trial_id', 'trial_rt', 'trial_fps', 'actual_duration_ms',
        'planned_duration_ms', 'duration_frames', 'actual_frame_count', 'dropped_frame_count',
        'trial_contrast', 'vehicle_size', 'central_vehicle', 'peripheral_vehicle', 'central_vehicle_click',
        'central_is_correct', 'peripheral_vehicle_click', 'peripheral_is_correct', 'final_rt',
        'user_reaction_time_ms', 'mouse_trajectory', 'actual_target_visual_angle',
    )
    assert row['trial_rt'] == 50.5
    assert row['user_reaction_time_ms'] == 202
    assert row['peripheral_vehicle'] is None
    assert exported['timing_invalid_repeats'] == 2
    assert exported['timing_stopped'] is False
    assert exported['experiment'] == 'Peripheral Field Assessment & Rehabilitation'
    assert exported['targetVisualAngle'] == '15.0°'
    assert exported['actualTargetVisualAngle'] == row['actual_target_visual_angle'] == '14.73°'
    assert exported['eccentricityClamped'] is True


def sample(subtest, mode, pixels=(1920, 1080)):
    config = validate_config(dict(selectedSubtest=subtest, selectedMode=mode, selectedAxes=[0, 2, 5]))
    config['subjectId'] = '編號,"A"\r\nB'
    trial = dict(
        dateTime='2026-02-03 04:05:05', practice=mode == 'practice', trialNumber=1,
        refreshHz=120, durationFrames=6, plannedDurationMs=50.01, durationMs=50.5, actualDurationMs=50.5,
        actualFrameCount=6, droppedFrameCount=0, contrast='100%', vehicleVisualAngle='2.5°',
        centralTarget='car', centralResponse='car', centralCorrect=True,
        peripheralCorrect=None, correct=True, responseTimeMs=201.5, mouseTrajectory=[dict(x=4, y=8, t=1)],
    )
    if subtest >= 2:
        trial.update(peripheralAxis=0, peripheralResponse=5, peripheralCorrect=False, correct=False)
    result = dict(
        trials=[trial, dict(trial, trialNumber=2, mouseTrajectory=[])],
        aborted=subtest == 3, thresholdMs=50.5, fastestMs=50.5, refreshHz=120, refreshMs=8.33,
        timingInvalidRepeats=2, timingStopped=False,
        geometry=calculate_screen_geometry(53.1, 29.9, 50, 15, 2.5, pixels),
    )
    return config, result
