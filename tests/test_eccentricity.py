import pytest

from ocufield.logic import calculate_screen_geometry, rendered_eccentricity


@pytest.mark.parametrize(('pixels', 'actual', 'clamped', 'limit', 'distance'), [
    ((1920, 1080), 14.734160066481744, True, 14.734160066481744, 49.07318915990665),
    ((2880, 1920), 15.0, False, 15.922479342367948, 53.23429277252421),
])
def test_default_rendered_eccentricity(pixels, actual, clamped, limit, distance):
    geometry = calculate_screen_geometry(53.1, 29.9, 50, 15, 2.5, pixels)
    result = rendered_eccentricity(geometry, 15, 50)
    assert result.actual_deg == pytest.approx(actual, rel=0, abs=1e-12)
    assert result.clamped is clamped
    assert result.render_limit_deg == pytest.approx(limit, rel=0, abs=1e-12)
    assert result.fit_distance_cm == pytest.approx(distance, rel=0, abs=1e-12)
    fit = calculate_screen_geometry(53.1, 29.9, result.fit_distance_cm, 15, 2.5, pixels)
    assert rendered_eccentricity(fit, 15, result.fit_distance_cm).actual_deg == pytest.approx(15, rel=0, abs=1e-12)


def test_lower_setting_renders_without_clamp():
    geometry = calculate_screen_geometry(53.1, 29.9, 50, 10, 2.5)
    result = rendered_eccentricity(geometry, 10, 50)
    assert result.actual_deg == pytest.approx(10, rel=0, abs=1e-12)
    assert not result.clamped


@pytest.mark.parametrize(('offset', 'clamped'), [(0.0049, False), (0.005, False), (0.0051, True)])
def test_clamp_warning_threshold_is_strict(offset, clamped):
    default = calculate_screen_geometry(53.1, 29.9, 50, 15, 2.5)
    limit = rendered_eccentricity(default, 15, 50).render_limit_deg
    target = limit + offset
    geometry = calculate_screen_geometry(53.1, 29.9, 50, target, 2.5)
    result = rendered_eccentricity(geometry, target, 50)
    assert result.actual_deg == limit
    assert result.clamped is clamped
