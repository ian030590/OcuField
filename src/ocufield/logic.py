from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from math import atan, degrees, floor, isfinite, radians, tan

DIRECTIONS = ('上', '右上', '右', '右下', '下', '左下', '左', '左上')
ARROWS = tuple('↑↗→↘↓↙←↖')
AXES = tuple(range(8))
COMPASS = (7, 0, 1, 6, None, 2, 5, 4, 3)
VEHICLES = {'car': '汽車', 'truck': '卡車'}
SUBTEST_NAMES = ('Processing Speed', 'Divided Attention', 'Selective Attention')
SUBTEST_TITLES = tuple(
    f'Subtest {i} {title} ({name})'
    for i, (title, name) in enumerate(zip(('處理速度', '分散注意力', '選擇性注意力'), SUBTEST_NAMES), 1)
)
INSTRUCTIONS = (
    '看著中央方框。刺激出現後，選出中央出現的是汽車或卡車。',
    '看著中央方框。刺激出現後，先選中央車輛，再選周邊目標出現的方向。',
    '看著中央方框。刺激出現後，在三角形干擾物中辨識中央車輛，並選出周邊目標方向。',
)

PRACTICE_TRIALS = 5
MIN_DURATION_FRAMES = 1
MAX_DURATION_MS = 500
PRACTICE_DURATION_MS = 250
FIXATION_MS = 1000
MASK_MS = 500
INTER_TRIAL_MS = 250
FEEDBACK_MS = 850
START_STEP_MS = 50
MIN_STEP_FRAMES = 1
OUTER_RING = 2
VEHICLE_WIDTH = 72
VEHICLE_HEIGHT = 56
MIN_TEST_TRIALS = 12
MAX_TEST_TRIALS = 60
MIN_STABLE_REVERSALS = 6
STABLE_REVERSAL_WINDOW = 6
FAIL_AT_MAX_LIMIT = 2
STABLE_LIMIT_STREAK = 3
CANDIDATE_HZ = (60, 75, 90, 100, 120, 144, 165, 180, 200, 240, 280, 300, 360, 480, 500, 540)


@dataclass(frozen=True)
class Slot:
    ring: int
    axis: int | None
    angleDeg: float
    isTargetCandidate: bool


SLOTS = tuple(
    Slot(ring, i // spacing if i % spacing == 0 else None,
         -90 + i * angle, ring == OUTER_RING and i % spacing == 0)
    for ring, (spacing, angle) in enumerate(((1, 45), (2, 22.5), (3, 15)))
    for i in range(8 * spacing)
)
TARGET_SLOTS = tuple(slot for slot in SLOTS if slot.isTargetCandidate)


def calculate_screen_geometry(width, height, distance, target, vehicle, pixels=(1920, 1080)):
    px_width, px_height = pixels
    ppcm = (px_width / max(1, width) + px_height / max(1, height)) / 2
    extent = min(width, height) / 2
    max_angle = degrees(atan(extent / max(1, distance)))
    over_limit = target > max_angle
    radius_cm = distance * tan(radians(target))
    vehicle_width = max(20, 2 * distance * tan(radians(vehicle / 2)) * ppcm)
    return dict(
        screenWidthPx=px_width, screenHeightPx=px_height, ppcm=ppcm,
        maxVisualAngleDeg=max_angle, isOverLimit=over_limit,
        suggestedDistanceCm=extent / tan(radians(target)) if over_limit else None,
        radiusPx=radius_cm * ppcm, vehicleWidthPx=vehicle_width,
        vehicleScale=vehicle_width / VEHICLE_WIDTH,
    )


def stage_dimensions(width, height, geometry=None):
    base = min(width, height)
    standard = base / 1080
    radius = base * 0.44
    vehicle_scale = (110 * standard * 0.58) / VEHICLE_WIDTH
    if geometry:
        if isfinite(geometry.get('radiusPx', float('nan'))):
            radius = min(radius, geometry['radiusPx'])
        if isfinite(geometry.get('vehicleScale', float('nan'))):
            vehicle_scale = geometry['vehicleScale']
    return dict(
        centerBoxSize=max(48, VEHICLE_WIDTH * vehicle_scale * 1.5),
        centerBoxBorder=max(2, 3 * standard),
        distractorWidth=92 * standard * (vehicle_scale / 0.88),
        distractorHeight=90 * standard * (vehicle_scale / 0.88),
        distractorStroke=max(2, 3.5 * standard),
        vehicleScale=vehicle_scale, radii=[radius * 0.333, radius * 0.666, radius],
    )


@dataclass(frozen=True)
class RenderedEccentricity:
    actual_deg: float
    clamped: bool
    render_limit_deg: float
    fit_distance_cm: float


def rendered_eccentricity(geometry, set_angle_deg, viewing_distance_cm):
    limit_px = stage_dimensions(geometry['screenWidthPx'], geometry['screenHeightPx'])['radii'][OUTER_RING]
    rendered_px = min(limit_px, geometry['radiusPx'])
    ppcm = geometry['ppcm']
    limit_cm = limit_px / ppcm
    actual_deg = degrees(atan((rendered_px / ppcm) / viewing_distance_cm))
    return RenderedEccentricity(
        actual_deg=actual_deg,
        clamped=set_angle_deg > actual_deg + 0.005,
        render_limit_deg=degrees(atan(limit_cm / viewing_distance_cm)),
        fit_distance_cm=limit_cm / tan(radians(set_angle_deg)),
    )


def js_round(value):
    lower = floor(value)
    return lower + (value - lower >= 0.5)


def fixed(value, places):
    precision = Decimal(1).scaleb(-places)
    return str(Decimal(value or 0).quantize(precision, rounding=ROUND_HALF_UP))


def round_ms(value):
    return float(fixed(value, 2))


def ms_to_frames(duration_ms, refresh_ms):
    if not isfinite(refresh_ms) or refresh_ms <= 0:
        refresh_ms = 1000 / 60
    return max(1, js_round(duration_ms / refresh_ms))


def frames_to_ms(frames, refresh_ms):
    return round_ms(frames * (refresh_ms if refresh_ms > 0 else 16.67))


def measure_refresh(intervals, discard=0):
    samples = [gap for gap in intervals if 1 <= gap <= 100]
    sorted_gaps = sorted(samples[discard:] or samples)
    measured = sorted_gaps[len(sorted_gaps) // 2] if sorted_gaps else 1000 / 60
    for hz in CANDIDATE_HZ:
        expected = 1000 / hz
        if abs(measured - expected) <= 0.85:
            return round_ms(expected), hz
    return round_ms(measured), max(1, js_round(1000 / measured))


def background_value(contrast):
    return js_round(255 * (1 - contrast / 100))


@dataclass
class Staircase:
    refreshMs: float
    testTrial: int = 0
    reversals: list[float] = field(default_factory=list)
    lastDirection: str | None = None
    limitStreak: int = 0
    failAtMaxStreak: int = 0
    minDurationFrames: int = MIN_DURATION_FRAMES
    maxDurationFrames: int = field(init=False)
    durationFrames: int = field(init=False)
    stepFrames: int = field(init=False)
    practiceDurationFrames: int = field(init=False)

    def __post_init__(self):
        self.maxDurationFrames = ms_to_frames(MAX_DURATION_MS, self.refreshMs)
        self.durationFrames = self.maxDurationFrames
        self.stepFrames = ms_to_frames(START_STEP_MS, self.refreshMs)
        self.practiceDurationFrames = ms_to_frames(PRACTICE_DURATION_MS, self.refreshMs)


def update_staircase(run, record):
    run.testTrial += 1
    correct = record['correct']
    direction = 'down' if correct else 'up'
    if run.lastDirection and run.lastDirection != direction:
        run.reversals.append(record['durationMs'])
        run.stepFrames = max(MIN_STEP_FRAMES, js_round(run.stepFrames * 0.75))
    run.lastDirection = direction
    delta = -run.stepFrames if correct else run.stepFrames * 3
    frames = record['durationFrames']
    next_frames = min(run.maxDurationFrames, max(run.minDurationFrames, frames + delta))
    at_limit = next_frames == frames and next_frames in (run.minDurationFrames, run.maxDurationFrames)
    run.limitStreak = run.limitStreak + 1 if at_limit else 0
    run.failAtMaxStreak = run.failAtMaxStreak + 1 if not correct and frames >= run.maxDurationFrames else 0
    run.durationFrames = next_frames


def has_stable_threshold(run):
    if run.testTrial < MIN_TEST_TRIALS or len(run.reversals) < MIN_STABLE_REVERSALS:
        return False
    recent = run.reversals[-STABLE_REVERSAL_WINDOW:]
    return max(recent) - min(recent) <= max(run.refreshMs * 3, 25)


def should_stop_adaptive_run(run, max_test_trials=MAX_TEST_TRIALS):
    limit = max(1, js_round(max_test_trials)) if isfinite(max_test_trials) else MAX_TEST_TRIALS
    return (
        run.failAtMaxStreak >= FAIL_AT_MAX_LIMIT
        or run.testTrial >= limit
        or has_stable_threshold(run)
        or (run.testTrial >= MIN_TEST_TRIALS and run.limitStreak >= STABLE_LIMIT_STREAK)
    )


def formal_trial_decision(run, stop_rule, limit):
    aborted = run.failAtMaxStreak >= FAIL_AT_MAX_LIMIT
    done = run.testTrial >= limit if stop_rule == 'fixed_trials' else should_stop_adaptive_run(run, limit)
    return done, aborted


def fastest_correct_stimulus_ms(trials, fallback=0):
    durations = []
    for trial in trials:
        if not trial['practice'] and trial['correct']:
            duration = trial.get('actualDurationMs') or trial['durationMs']
            if isfinite(duration) and duration > 0:
                durations.append(duration)
    return round_ms(min(durations, default=fallback))


def estimate_threshold_ms(run, trials, fallback):
    if run.limitStreak >= STABLE_LIMIT_STREAK:
        return fastest_correct_stimulus_ms(trials, fallback)
    if len(run.reversals) >= 4:
        recent = run.reversals[-STABLE_REVERSAL_WINDOW:]
        return round_ms(sum(recent) / len(recent))
    return round_ms(fallback)


def percent(correct, total):
    return js_round(correct / total * 100) if total else 0


def direction_name(axis, missing):
    return missing if axis is None else DIRECTIONS[int(axis)] if axis in AXES else str(axis)


def direction_stats(formal_trials):
    for axis, name in enumerate(DIRECTIONS):
        trials = [trial for trial in formal_trials if trial.get('peripheralAxis') == axis]
        total = len(trials)
        correct = sum(trial['correct'] for trial in trials)
        rt = js_round(sum(trial['responseTimeMs'] for trial in trials) / total) if total else 0
        duration = round_ms(sum(trial['actualDurationMs'] for trial in trials) / total) if total else 0
        yield axis, name, total, correct, percent(correct, total) if total else None, rt, duration
