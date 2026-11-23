from itertools import accumulate, repeat
from types import SimpleNamespace

import pytest

from ocufield import experiment
from ocufield.logic import FIXATION_MS
from ocufield.storage import validate_config
from ocufield.timing import (
    CADENCE_TIMEOUT_MS, MAX_TIMING_RETRIES, TIMING_ERROR, CadenceError, StimulusOverrun,
    stimulus_timing, wait_for_cadence,
)

NOMINAL_MS = 8.33


def simulated_flips(intervals):
    timestamps = (ms / 1000 for ms in accumulate(intervals, initial=0))
    return lambda: next(timestamps)


def test_gate_waits_for_recent_nominal_cadence():
    intervals = [NOMINAL_MS] * 115 + [0.6, 66.9, 66.9, 66.9]
    minimum = sum(intervals) / 1000
    flip = simulated_flips([*intervals, *[8.3, 8.6] * 5])
    assert wait_for_cadence(flip, NOMINAL_MS, FIXATION_MS) == pytest.approx(minimum + 0.0845)


def test_gate_rejects_sustained_15_hz_and_late_recovery():
    flip = simulated_flips([66.9] * 46 + [NOMINAL_MS] * 40)
    with pytest.raises(CadenceError, match=TIMING_ERROR):
        wait_for_cadence(flip, NOMINAL_MS, FIXATION_MS)
    assert CADENCE_TIMEOUT_MS / 1000 <= flip() < 3.2


def test_dropped_frames_use_nominal_period():
    assert stimulus_timing(1.0, 1.025, 3, NOMINAL_MS) == (25, 0)
    with pytest.raises(StimulusOverrun) as one:
        stimulus_timing(1.0, 1.03333, 3, NOMINAL_MS)
    assert one.value.dropped_frames == 1
    with pytest.raises(StimulusOverrun) as collapse:
        stimulus_timing(1.0, 1.19959, 3, NOMINAL_MS)
    assert (collapse.value.actual_ms, collapse.value.dropped_frames) == (199.59, 21)


@pytest.mark.parametrize(('outcomes', 'expected_attempts', 'stopped', 'discarded'), [
    (('valid', 'overrun', 'valid'), [(1, 60), (2, 54), (2, 54)], False, 1),
    (('valid', *repeat('overrun', MAX_TIMING_RETRIES + 1)), [(1, 60), *repeat((2, 54), 3)], True, 3),
    (('valid', 'gate failure'), [(1, 60), (2, 54)], True, 0),
    (('gate failure',), [(1, 60)], True, 0),
])
def test_timing_invalid_attempts_never_reach_scoring(monkeypatch, outcomes, expected_attempts, stopped, discarded):
    attempts = []
    observed_by_staircase = []
    outcomes = iter(outcomes)
    window = SimpleNamespace(_hw_handle=123, close=lambda: None)
    visual = SimpleNamespace(Window=lambda **_: window)
    display = SimpleNamespace(
        size=(2880, 1920), initial_refresh=lambda ms: wait_for_cadence(simulated_flips(repeat(ms)), ms, 24 * ms),
        close=lambda: None, central=(None,),
    )
    monkeypatch.setattr(experiment, 'Display', lambda *_: display)
    monkeypatch.setattr(experiment, 'monitor_refresh_hz', lambda hwnd: {123: 120}[hwnd])
    real_update = experiment.update_staircase

    def update(run, record):
        observed_by_staircase.append(record['trialNumber'])
        real_update(run, record)

    def trial(_display, _config, run, _geometry, practice, number, _rng, _noise, _scripted, _delay, hz):
        outcome = next(outcomes)
        frames = run.durationFrames
        attempts.append((number, frames))
        assert hz == 120 and run.refreshMs == NOMINAL_MS
        if outcome == 'gate failure':
            wait_for_cadence(simulated_flips(repeat(66.9)), run.refreshMs, FIXATION_MS)
        actual, dropped = stimulus_timing(1, 1 + frames * (66.9 if outcome == 'overrun' else NOMINAL_MS) / 1000,
                                          frames, run.refreshMs)
        return dict(trialNumber=number, practice=practice, correct=True, durationFrames=frames,
                    durationMs=actual, droppedFrameCount=dropped), 2

    monkeypatch.setattr(experiment, 'trial', trial)
    monkeypatch.setattr(experiment, 'update_staircase', update)
    config = validate_config(dict(stopConditionType='fixed_trials', selectedTrialCount=2))
    result = experiment.run_experiment(visual, config, fullscreen=False)
    assert attempts == expected_attempts
    assert result['timingStopped'] == result['aborted'] == stopped
    assert result['timingInvalidRepeats'] == discarded
    assert result['refreshHz'] == 120
    assert (result['thresholdMs'] is None) == stopped
    expected_scored_trials = [] if expected_attempts == [(1, 60)] else [1] if stopped else [1, 2]
    assert [t['trialNumber'] for t in result['trials']] == observed_by_staircase == expected_scored_trials


def test_numbers_are_ignored_and_escape_still_aborts():
    display = experiment.Display.__new__(experiment.Display)
    display.escape = 65307
    display.cancelled = False
    display.responding = True
    display.responses = []
    for digit in '12345678':
        assert display.on_key(ord(digit), 0) is None
    assert not display.responses and not display.cancelled
    assert display.on_key(display.escape, 0) is True and display.cancelled
