from datetime import datetime
import json

from .logic import (
    INSTRUCTIONS, SUBTEST_NAMES, SUBTEST_TITLES, VEHICLES, direction_name,
    direction_stats, fixed, js_round, percent, rendered_eccentricity, round_ms,
)
from .storage import write_file

RAW_HEADERS = (
    '受試者代號', '測驗日期', '測驗時間', 'Subtest項目代碼', 'Subtest項目名稱', '題次序號',
    '題次類型', '設定呈現時間 (ms)', '實際呈現時間 (ms)', '呈現影格數', '遺失影格數',
    '螢幕更新率 (Hz)', '對比度 (%)', '車輛大小視角 (度)', '周邊偏心視角 (度)',
    '中央目標種類', '中央作答選擇', '中央作答正確', '周邊目標方位代碼', '周邊目標方位名稱',
    '周邊作答選擇代碼', '周邊作答選擇名稱', '周邊作答正確', '本題整體判定', '作答反應時間 (ms)',
    '滑鼠軌跡取樣數', '滑鼠軌跡數據 (JSON)', '實際周邊偏心視角 (度)',
)
STAT_HEADERS = ('參數項目', '參數代碼', '設定數值', '單位', '詳細說明')
DATE_TIME = '%Y-%m-%d %H:%M:%S'


def number_text(value):
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def escape(value):
    return '"' + ('' if value is None else number_text(value).replace('"', '""')) + '"'


def csv_bytes(headers, rows):
    return '\r\n'.join([','.join(headers), *(','.join(row) for row in rows)]).encode('utf-8-sig')


def truth(value, missing=''):
    return 'TRUE' if value is True else 'FALSE' if value is False else missing


def raw_rows(config, result, when, actual_angle):
    subtest = config['selectedSubtest']
    code = f'Subtest {subtest}'
    target_angle = fixed(config['targetVisualAngleDeg'], 1) + '°'
    for index, trial in enumerate(result['trials'], 1):
        axis = trial.get('peripheralAxis')
        response = trial.get('peripheralResponse')
        trajectory = trial['mouseTrajectory']
        yield (
            escape(config['subjectId'] or '-'), escape(when.date().isoformat()),
            escape(when.strftime('%H:%M:%S')), escape(code), escape(SUBTEST_NAMES[subtest - 1]),
            number_text(trial.get('trialNumber') or index), escape('練習題' if trial['practice'] else '正式題'),
            number_text(round_ms(trial.get('plannedDurationMs') or trial.get('durationMs') or 0)),
            number_text(round_ms(trial.get('actualDurationMs') or trial.get('durationMs') or 0)),
            number_text(trial.get('actualFrameCount') or trial.get('durationFrames') or 0),
            number_text(trial.get('droppedFrameCount') or 0), number_text(trial.get('refreshHz') or result['refreshHz']),
            escape(trial['contrast']), escape(trial['vehicleVisualAngle']), escape(target_angle),
            escape(VEHICLES.get(trial['centralTarget'], trial['centralTarget'])),
            escape(VEHICLES.get(trial['centralResponse'], trial['centralResponse'])),
            escape(truth(trial['centralCorrect'])), escape('N/A' if axis is None else axis),
            escape(direction_name(axis, '無周邊目標')), escape('N/A' if response is None else response),
            escape(direction_name(response, '無周邊作答')), escape(truth(trial['peripheralCorrect'], 'N/A')),
            escape(truth(trial['correct'], 'FALSE')), number_text(js_round(trial['responseTimeMs'])),
            number_text(len(trajectory)), escape(json.dumps(trajectory, separators=(',', ':'))), escape(actual_angle),
        )


def stat_rows(config, result, when, eccentricity):
    subtest = config['selectedSubtest']
    geometry = result['geometry']
    formal = [t for t in result['trials'] if not t['practice']]
    total = len(formal)
    correct = sum(t['correct'] for t in formal)
    central = percent(sum(t['centralCorrect'] for t in formal), total)
    peripheral = [t for t in formal if t.get('peripheralAxis') is not None]
    peri_accuracy = percent(sum(t['peripheralCorrect'] for t in peripheral), len(peripheral))
    rt = js_round(sum(t['responseTimeMs'] for t in formal) / total) if total else 0
    axes = config['selectedAxes']
    enabled = '、'.join(direction_name(axis, '') for axis in axes)
    axis_codes = ', '.join(map(number_text, axes))
    mode = config['selectedMode']
    stop = config['stopConditionType']
    mode_label = dict(formal='正式紀錄 (Formal)', practice='練習模式 (Practice)', instruction='說明模式 (Instruction)')[mode]
    count = number_text(config['selectedTrialCount'])
    stop_label = '80%信度自適應階梯 (Adaptive 80%)' if stop == 'adaptive_80' else f'固定題數 ({count} 題)'
    resolution = f"{geometry['screenWidthPx']} × {geometry['screenHeightPx']}"
    aborted = result['aborted']
    ms, pct, cm, deg, px = 'ms (毫秒)', '% (百分比)', 'cm (公分)', 'deg (度 / °)', 'px (像素)'
    yield from (
        ('測驗日期', 'test_date', when.date().isoformat(), 'YYYY-MM-DD', '測驗進行日期'),
        ('測驗時間', 'test_time', when.strftime('%H:%M:%S'), 'HH:mm:ss', '測驗完成時間'),
        ('受試者代號', 'subject_id', config['subjectId'] or '-', '-', '受試者識別碼'),
        ('測驗項目代碼', 'subtest_code', f'Subtest {subtest}', '-', '周邊視野測驗核心項目'),
        ('測驗項目名稱', 'subtest_name', SUBTEST_TITLES[subtest - 1], '-', INSTRUCTIONS[subtest - 1]),
        ('測驗模式', 'test_mode', mode_label, '-', mode),
        ('終止條件設定', 'stop_condition', stop_label, '-', stop),
        ('處理速度反應門檻 (final_rt)', 'final_threshold_rt_ms', result['thresholdMs'], ms, '階梯法自動收斂出信度80%之處理速度門檻'),
        ('最快正確呈現時間', 'fastest_correct_duration_ms', result['fastestMs'], ms, '測驗中正確辨識之最短刺激呈現時間'),
        ('正式題總題數', 'formal_trials_total', total, '題', '正式測驗完成題數'),
        ('正式題正確題數', 'formal_trials_correct', correct, '題', '正式測驗答對題數'),
        ('正式題錯誤題數', 'formal_trials_incorrect', total - correct, '題', '正式測驗答錯題數'),
        ('整體正確率', 'accuracy_rate_percent', f'{percent(correct, total)}%', pct, '正式測驗正確作答比例'),
        ('中央目標正確率', 'central_accuracy_percent', f'{central}%', pct, '中央車輛辨識正確率'),
        ('周邊目標正確率', 'peripheral_accuracy_percent', f'{peri_accuracy}%' if peripheral else 'N/A',
         pct if peripheral else '-', '周邊方位搜尋正確率' if subtest >= 2 else '此Subtest不包含周邊目標'),
        ('平均作答反應時間', 'mean_response_time_ms', rt, ms, '受試者自題目出現至點擊完成之平均作答反應時間'),
        ('練習題完成題數', 'practice_trials_count', len(result['trials']) - total, '題', '測驗前進行之練習題數'),
        ('螢幕物理寬度', 'screen_width_cm', config['screenWidthCm'], cm, '校準設定之螢幕物理寬度'),
        ('螢幕物理高度', 'screen_height_cm', config['screenHeightCm'], cm, '校準設定之螢幕物理高度'),
        ('觀看距離', 'viewing_distance_cm', config['viewingDistanceCm'], cm, '受試者與螢幕之設定距離'),
        ('螢幕像素解析度', 'screen_resolution_px', resolution, px, '螢幕水平與垂直像素解析度'),
        ('計算像素密度', 'pixel_density_ppcm', js_round(geometry['ppcm']), 'PPCM (像素/公分)', '螢幕每公分像素密度'),
        ('螢幕支援極限視角', 'max_visual_angle_deg', fixed(geometry['maxVisualAngleDeg'], 2), deg, '依觀看距離與螢幕尺寸可測之最大極限半徑視角'),
        ('周邊偏心視角設定', 'target_visual_angle_deg', fixed(config['targetVisualAngleDeg'], 1), deg, '周邊目標刺激物偏心視角'),
        ('車輛大小視角設定', 'vehicle_visual_angle_deg', fixed(config['vehicleVisualAngleDeg'], 1), deg, '車輛刺激物大小視角'),
        ('車輛像素渲染大小', 'vehicle_size_px', f"{js_round(geometry['vehicleWidthPx'])} px", px, '車輛刺激物螢幕像素尺寸'),
        ('刺激對比度設定', 'contrast_percent', number_text(config['contrastPercent']) + '%', pct, '刺激物與背景之對比強度 (目標物為白，調整底色階度)'),
        ('啟用刺激方向數量', 'enabled_direction_count', len(axes), '個', f'已啟用 {len(axes)} / 8 個方位'),
        ('啟用刺激方向列表', 'enabled_direction_list', enabled, '-', axis_codes),
        ('螢幕即時更新率', 'refresh_rate_hz', result['refreshHz'], 'Hz (赫茲)', 'rAF 實測畫面更新頻率 (FPS)'),
        ('影格刷新間隔', 'frame_interval_ms', result['refreshMs'], ms, '單一影格持續時間'),
        ('測驗結束狀態', 'test_aborted', '中斷 (Aborted)' if aborted else '正常完成 (Completed)', '-',
         '因達到連續失敗上限或中斷' if aborted else '正常完成設定題數或收斂門檻'),
    )
    for axis, name, count, correct, accuracy, rt, _ in direction_stats(formal):
        yield (
            f'8方向空間搜尋-{name} ({axis})', f'spatial_dir_{axis}_{name}',
            f'{accuracy}%' if accuracy is not None else '未測試', pct if accuracy is not None else '-',
            f"呈現 {count} 次, 答對 {correct} 次, 平均作答耗時 {f'{rt} ms' if rt > 0 else 'N/A'}",
        )
    yield ('實際周邊偏心視角', 'actual_target_visual_angle_deg', fixed(eccentricity.actual_deg, 2), deg,
           '依測驗畫面像素尺寸換算的周邊目標刺激物偏心視角')
    yield ('周邊偏心視角受限', 'eccentricity_clamped', truth(eccentricity.clamped), '-',
           '設定視角與實際視角相差超過 0.005 度')


def write_csvs(directory, config, result, when=None):
    when = when or datetime.now()
    prefix = f"{when:%Y%m%d-%H%M%S}-Subtest{config['selectedSubtest']}"
    raw = directory / f'{prefix}-原始分數.csv'
    stats = directory / f'{prefix}-統計成績.csv'
    eccentricity = rendered_eccentricity(result['geometry'], config['targetVisualAngleDeg'], config['viewingDistanceCm'])
    actual_angle = fixed(eccentricity.actual_deg, 2) + '°'
    write_file(raw, csv_bytes(RAW_HEADERS, raw_rows(config, result, when, actual_angle)), replace=False)
    rows = (tuple(map(escape, row)) for row in stat_rows(config, result, when, eccentricity))
    write_file(stats, csv_bytes(STAT_HEADERS, rows), replace=False)
    return raw, stats


def json_data(config, result, when):
    subject = config['subjectId']
    threshold = result['thresholdMs']
    eccentricity = rendered_eccentricity(result['geometry'], config['targetVisualAngleDeg'], config['viewingDistanceCm'])
    actual_angle = fixed(eccentricity.actual_deg, 2) + '°'
    trials = [
        dict(
            subjectId=subject, date_time=t['dateTime'], trial_id=t['trialNumber'],
            trial_rt=round_ms(t['actualDurationMs'] or t['durationMs'] or 0),
            trial_fps=t['refreshHz'] or result['refreshHz'], actual_duration_ms=t['actualDurationMs'],
            planned_duration_ms=t['plannedDurationMs'], duration_frames=t['durationFrames'],
            actual_frame_count=t['actualFrameCount'], dropped_frame_count=t['droppedFrameCount'],
            trial_contrast=t['contrast'], vehicle_size=t['vehicleVisualAngle'],
            central_vehicle=t['centralTarget'], peripheral_vehicle=direction_name(t.get('peripheralAxis'), None),
            central_vehicle_click=t['centralResponse'], central_is_correct=t['centralCorrect'],
            peripheral_vehicle_click=direction_name(t.get('peripheralResponse'), None),
            peripheral_is_correct=t['peripheralCorrect'], final_rt=threshold,
            user_reaction_time_ms=js_round(t['responseTimeMs']), mouse_trajectory=t['mouseTrajectory'],
            actual_target_visual_angle=actual_angle,
        )
        for t in result['trials']
    ]
    return dict(
        experiment='Peripheral Field Assessment & Rehabilitation', version='2.0.0-clinical',
        date_time=when.strftime(DATE_TIME), subjectId=subject, subtestId=config['selectedSubtest'],
        contrast=number_text(config['contrastPercent']) + '%',
        targetVisualAngle=fixed(config['targetVisualAngleDeg'], 1) + '°',
        vehicleVisualAngle=fixed(config['vehicleVisualAngleDeg'], 1) + '°',
        final_rt=threshold, refreshHz=result['refreshHz'], refreshMs=result['refreshMs'],
        timing_invalid_repeats=result['timingInvalidRepeats'], timing_stopped=result['timingStopped'], trials=trials,
        actualTargetVisualAngle=actual_angle, eccentricityClamped=eccentricity.clamped,
    )


def write_json(path, data):
    write_file(path, json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8'))
