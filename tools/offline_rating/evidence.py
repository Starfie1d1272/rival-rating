"""Bookkeeping consistency is not an independent observation of event order."""

import math


def check_derived_hurt_bookkeeping(rows):
    """Check the cs2df 3.1.0 cumulative columns, keeping their evidence level.

    These columns start at 100 per round/victim and are generated in retained
    hurt order. Even a unique consistent chain cannot prove actual same-tick
    order. No event reordering, damage correction or score modification occurs.
    """
    health = {}
    failures = []
    for index, row in enumerate(rows):
        raw = row['healthDamageRaw']
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw):
            raise ValueError('healthDamageRaw must be a finite number, not bool')
        key = (row['roundNumber'], row['victimIndex'])
        before = health.get(key, 100.)
        removed = min(max(raw, 0.), before)
        if row['victimHealthBefore'] != before or row['healthDamage'] != removed:
            failures.append({'index': index, 'expectedBefore': before,
                             'expectedCappedDamage': removed})
        health[key] = before - removed
    return {
        'bookkeepingConsistent': not failures,
        'bookkeepingFailures': failures,
        'independentOrderEvidence': 'not_established',
        'actualSameTickOrder': 'unknown',
        'beforeOrigin': 'exporter_derived_cumulative',
        'sourceIndexRole': 'retained_order_convention',
    }
