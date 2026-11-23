from .logic import js_round, round_ms

TIMING_ERROR = '螢幕更新時序不穩定，測驗已中止。'
CADENCE_INTERVALS = 10
CADENCE_TOLERANCE = 0.125
CADENCE_TIMEOUT_MS = 3000
MAX_TIMING_RETRIES = 2


class CadenceError(RuntimeError):
    pass


class StimulusOverrun(Exception):
    def __init__(self, actual_ms, dropped_frames):
        self.actual_ms = actual_ms
        self.dropped_frames = dropped_frames
        super().__init__(f'{actual_ms} ms, {dropped_frames} dropped frames')


def wait_for_cadence(flip, nominal_ms, minimum_ms):
    start = previous = flip()
    stable = 0
    while True:
        timestamp = flip()
        gap = (timestamp - previous) * 1000
        elapsed = (timestamp - start) * 1000
        if elapsed >= CADENCE_TIMEOUT_MS:
            raise CadenceError(TIMING_ERROR)
        stable = stable + 1 if abs(gap - nominal_ms) <= nominal_ms * CADENCE_TOLERANCE else 0
        if elapsed >= minimum_ms and stable >= CADENCE_INTERVALS:
            return timestamp
        previous = timestamp


def stimulus_timing(onset, mask_onset, frames, nominal_ms):
    actual_ms = round_ms((mask_onset - onset) * 1000)
    dropped = max(0, js_round(actual_ms / nominal_ms) - frames)
    if dropped:
        raise StimulusOverrun(actual_ms, dropped)
    return actual_ms, dropped
