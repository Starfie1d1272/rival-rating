"""Export already fitted/validated parameters; never train or unpickle objects."""

import json

from .heads import validate_package


def _numbers(values):
    return [float(value) for value in values]


def export_head(head, feature_names, source_file, source_sha256, head_sha256):
    """Convert the reviewed fitted-head attributes to portable JSON values.

    The caller supplies an in-memory head and provenance. There is deliberately
    no binary loader here. Coefficients, scaler order and bounds are unchanged.
    Complete packages must pass validate_package before serialization.
    """
    if head['kind'] == 'poisson':
        coef = head['model'].coef_
        intercept = head['model'].intercept_
    else:
        coef = head['coef'][1:]
        intercept = head['coef'][0]
    return dict(
        kind=head['kind'], features=list(feature_names), vocab=list(head['vocab']),
        mean=_numbers(head['scaler'].mean_), scale=_numbers(head['scaler'].scale_),
        coef=_numbers(coef), intercept=float(intercept), bound=head.get('bound'),
        doseScale=_numbers(head['doseScale']) if 'doseScale' in head else None,
        mix=_numbers(head['mix']) if 'mix' in head else None,
        alpha=float(head['alpha']), sourceFile=source_file,
        sourceSHA256=source_sha256, sourceHeadSHA256=head_sha256,
    )


def export_json(package):
    """Round-trip-safe serialization, with strict validation before output."""
    validate_package(package)
    return json.dumps(package, ensure_ascii=False, allow_nan=False, indent=2) + '\n'
