"""Explicit host-only bridge to the actual NYCH M-Gate requirement API."""
from .gates import Evaluation, Outcome

REF = 'nych.operation-text@1'
REQUIREMENT = 'Proposed write text equals the NYCH checkpoint plus one newline.'


def operation_text(context, condition):
    from nych.gates import AtomicRequirement, GateOutcome
    arguments = context['operation']['arguments']
    expected = context['current']['nych']['encoded'] + '\n'

    def compare():
        return (GateOutcome.PASS if arguments['text'] == expected else GateOutcome.FAIL,
                'NYCH checkpoint text comparison')

    # Missing input deliberately leaves the real requirement unbound; NYCH's
    # own no-evaluator rule returns UNKNOWN, not a fabricated successful result.
    atomic = AtomicRequirement(condition['req_id'], condition['requirement'],
                               evaluator=compare if 'text' in arguments else None)
    raw, reason = atomic.evaluate()
    mapped = Outcome(raw) if raw in ('PASS', 'FAIL', 'UNKNOWN') else Outcome.UNKNOWN
    return Evaluation(mapped, reason, {'implementation': 'nych.gates.AtomicRequirement',
                                      'raw_outcome': raw})
