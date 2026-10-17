"""Frozen G8SON sources and host-bound, fail-closed three-valued evaluation."""
from enum import Enum
from dataclasses import dataclass, field
import hashlib
import json
import math
import re
import types


def _copy(value):
    def check(x):
        if x is None or type(x) in (str, bool, int):
            return
        if type(x) is float and math.isfinite(x):
            return
        if type(x) is list:
            for item in x:
                check(item)
            return
        if type(x) is dict and all(type(k) is str for k in x):
            for item in x.values():
                check(item)
            return
        raise ValueError('finite JSON values with string keys required')
    check(value)
    return json.loads(json.dumps(value, allow_nan=False))


def _digest(value):
    raw = json.dumps(_copy(value), sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(label + ' must be a nonempty string')
    return value


def _scalar(value):
    return value is None or type(value) in (str, bool, int) or (type(value) is float and math.isfinite(value))


def _pointer(path):
    if not isinstance(path, str) or not path.startswith('/') or re.search(r'~(?![01])', path):
        raise ValueError('invalid JSON Pointer')
    parts = [p.replace('~1', '/').replace('~0', '~') for p in path[1:].split('/')]
    if parts[0] not in ('current', 'candidate', 'operation', 'evidence'):
        raise ValueError('pointer must start at current, candidate, operation or evidence')
    return parts


def _validate_condition(condition):
    if not isinstance(condition, dict):
        raise ValueError('condition must be an object')
    if 'evaluator_ref' in condition:
        _text(condition['evaluator_ref'], 'evaluator_ref')
    elif not any(key in condition for key in ('path', 'op', 'value')) and condition.get('requirement'):
        _text(condition['requirement'], 'requirement')
    else:
        _pointer(condition.get('path'))
        if condition.get('op') not in ('eq', 'ne', 'gt', 'gte', 'lt', 'lte'):
            raise ValueError('unsupported predicate operator')
        if 'value' not in condition or not _scalar(condition['value']):
            raise ValueError('comparison requires finite scalar literal')
        if condition['op'] not in ('eq', 'ne') and type(condition['value']) not in (int, float):
            raise ValueError('ordered comparison requires numeric literal')
    if 'evidence_kind' in condition:
        _text(condition['evidence_kind'], 'evidence_kind')


class Outcome(str, Enum):
    PASS = 'PASS'
    FAIL = 'FAIL'
    UNKNOWN = 'UNKNOWN'


@dataclass(frozen=True)
class Evaluation:
    outcome: Outcome
    reason: str
    evidence: dict = field(default_factory=dict)


def _constant_snapshot(value):
    if isinstance(value, types.CodeType):
        return {'code': _code_snapshot(value)}
    if isinstance(value, bytes):
        return {'bytes': value.hex()}
    if isinstance(value, (tuple, frozenset)):
        items = [_constant_snapshot(item) for item in value]
        if isinstance(value, frozenset):
            items.sort(key=lambda item: json.dumps(item, sort_keys=True))
        return {'type': type(value).__name__, 'items': items}
    # Other code constants are immutable scalar literals, never live callables.
    return {'type': type(value).__name__, 'literal': repr(value)}


def _code_snapshot(code):
    if not isinstance(code, types.CodeType):
        return None
    return {'bytecode': code.co_code.hex(),
            'exceptions': getattr(code, 'co_exceptiontable', b'').hex(),
            'constants': [_constant_snapshot(value) for value in code.co_consts],
            'names': list(code.co_names), 'vars': list(code.co_varnames),
            'freevars': list(code.co_freevars), 'flags': code.co_flags,
            'args': [code.co_argcount, code.co_posonlyargcount, code.co_kwonlyargcount]}


def _referenced_names(code):
    """Include globals read by nested lambdas, generators and comprehensions."""
    if not isinstance(code, types.CodeType):
        return []
    names = set(code.co_names)
    for constant in code.co_consts:
        if isinstance(constant, types.CodeType):
            names.update(_referenced_names(constant))
    return sorted(names)


def _configuration_snapshot(value, seen=None):
    """Hash inspectable callback configuration without inventing opaque semantics.

    Globals/defaults/closures containing JSON-like values are tracked. Modules,
    classes and opaque objects remain explicit versioned host dependencies.
    """
    if value is None or type(value) in (str, bool, int, float):
        return _copy(value)
    seen = set() if seen is None else seen
    if id(value) in seen:
        return {'dependency': 'cyclic', 'type': type(value).__qualname__}
    seen = seen | {id(value)}
    if type(value) in (list, tuple):
        return {'sequence_type': type(value).__name__, 'values': [_configuration_snapshot(v, seen) for v in value]}
    if type(value) is dict and all(type(k) is str for k in value):
        return {k: _configuration_snapshot(v, seen) for k, v in sorted(value.items())}
    if isinstance(value, types.FunctionType):
        return {'function': value.__module__ + '.' + value.__qualname__, 'code': _code_snapshot(value.__code__)}
    if isinstance(value, types.ModuleType):
        return {'module': value.__name__, 'version': str(getattr(value, '__version__', 'host-versioned'))}
    if isinstance(value, type):
        return {'class': value.__module__ + '.' + value.__qualname__}
    return {'opaque_dependency': type(value).__module__ + '.' + type(value).__qualname__}


class Registry:
    """Only host code registers callables; references never import or execute source."""

    def __init__(self):
        self._entries = {}

    def register(self, ref: str, evaluator, *, kind: str = 'mechanical', version: str = '1') -> None:
        _text(ref, 'ref')
        _text(kind, 'kind')
        _text(version, 'version')
        if ref in self._entries:
            raise ValueError('duplicate evaluator reference: ' + ref)
        if not callable(evaluator):
            raise ValueError('evaluator must be callable')
        self._entries[ref] = (evaluator, kind, version)

    def fingerprint(self) -> str:
        entries = []
        for ref, (fn, kind, version) in sorted(self._entries.items()):
            code = getattr(fn, '__code__', None)
            if code is None:
                code = getattr(getattr(fn, '__call__', None), '__code__', None)
            entries.append({'ref': ref, 'kind': kind, 'version': version,
                            'module': getattr(fn, '__module__', type(fn).__module__),
                            'name': getattr(fn, '__qualname__', type(fn).__qualname__),
                            'code_digest': _digest(_code_snapshot(code)) if code is not None else None,
                            'defaults': _configuration_snapshot(getattr(fn, '__defaults__', None)),
                            'keyword_defaults': _configuration_snapshot(getattr(fn, '__kwdefaults__', None)),
                            'closure': [_configuration_snapshot(cell.cell_contents) for cell in (getattr(fn, '__closure__', None) or ())],
                            'globals': {name: _configuration_snapshot(fn.__globals__[name])
                                        for name in _referenced_names(code)
                                        if name in getattr(fn, '__globals__', {})}})
        return _digest(entries)

    def evaluate(self, condition: dict, context: dict) -> Evaluation:
        try:
            _validate_condition(condition)
            if 'evaluator_ref' in condition:
                entry = self._entries.get(condition['evaluator_ref'])
                if entry is None:
                    return Evaluation(Outcome.UNKNOWN, 'evaluator not registered: ' + condition['evaluator_ref'])
                result = entry[0](_copy(context), _copy(condition))
                if (not isinstance(result, Evaluation) or not isinstance(result.outcome, Outcome)
                        or not isinstance(result.reason, str) or not isinstance(result.evidence, dict)):
                    return Evaluation(Outcome.UNKNOWN, 'invalid evaluator result')
                evidence = _copy(result.evidence)
                evidence['evaluator'] = {'ref': condition['evaluator_ref'], 'kind': entry[1], 'version': entry[2]}
                return Evaluation(result.outcome, result.reason, evidence)
            if 'path' not in condition:
                return Evaluation(Outcome.UNKNOWN, 'requirement has no evaluator binding')
            path = condition['path']
            value = context
            for token in _pointer(path):
                if isinstance(value, dict):
                    value = value[token]
                elif isinstance(value, list) and re.fullmatch(r'0|[1-9][0-9]*', token):
                    value = value[int(token)]
                else:
                    return Evaluation(Outcome.UNKNOWN, 'missing or invalid path: ' + path)
            kind = context.get('_provenance', {}).get(path)
            if 'evidence_kind' in condition and kind != condition['evidence_kind']:
                return Evaluation(Outcome.UNKNOWN, 'insufficient provenance: ' + path)
            expected = condition['value']
            if not _scalar(value):
                return Evaluation(Outcome.UNKNOWN, 'resolved value is not a finite scalar')
            both_numbers = type(value) in (int, float) and type(expected) in (int, float)
            if type(value) is not type(expected) and not both_numbers:
                return Evaluation(Outcome.UNKNOWN, 'incompatible scalar types')
            op = condition['op']
            if op not in ('eq', 'ne') and not both_numbers:
                return Evaluation(Outcome.UNKNOWN, 'ordered comparison requires finite numbers')
            if op == 'eq':
                passed = value == expected
            elif op == 'ne':
                passed = value != expected
            elif op == 'gt':
                passed = value > expected
            elif op == 'gte':
                passed = value >= expected
            elif op == 'lt':
                passed = value < expected
            else:
                passed = value <= expected
            evidence = {'path': path, 'value': value, 'expected': expected, 'op': op, 'kind': kind}
            return Evaluation(Outcome.PASS if passed else Outcome.FAIL, 'comparison ' + op, _copy(evidence))
        except Exception as exc:
            return Evaluation(Outcome.UNKNOWN, 'evaluation error: ' + type(exc).__name__ + ': ' + str(exc))


_ROUTES = frozenset(('continue', 'commit', 'reject', 'stop', 'review', 'repeat'))
_CANONICAL = {Outcome.PASS: 'PASS', Outcome.FAIL: 'FAIL', Outcome.UNKNOWN: 'INTERMEDIATE'}


def _routes(value):
    if not isinstance(value, dict) or set(value) != {'PASS', 'FAIL', 'INTERMEDIATE'}:
        raise ValueError('all three canonical outcomes must have explicit routes')
    if any(not isinstance(route, str) or route not in _ROUTES for route in value.values()):
        raise ValueError('unsupported route')


class GateSet:
    """Validated source snapshot plus separately identified reviewed bindings.

    Historical files without file_id use their original gate_id as file identity.
    Bindings never overwrite authored requirement text or identifiers.
    """

    def __init__(self, document: dict, bindings: dict | None = None):
        if not isinstance(document, dict) or (bindings is not None and not isinstance(bindings, dict)):
            raise ValueError('document and bindings must be objects')
        self._document = _copy(document)
        self._bindings = _copy(bindings if bindings is not None else {})
        self._fingerprint = _digest({'source': self._document, 'bindings': self._bindings})
        self._gates = []
        requirements = self._bindings.get('requirements', {})
        if not isinstance(requirements, dict):
            raise ValueError('requirements binding must be an object')
        historical = 'atomic_requirements' in document
        if historical:
            if 'gates' in document or 'g8son_version' in document:
                raise ValueError('ambiguous source profile')
            gate_id = _text(document.get('gate_id'), 'gate_id')
            self._file_id = _text(document.get('file_id', gate_id), 'file_id')
            source_gates = [{'gate_id': gate_id, 'type': self._bindings.get('operator'),
                             'conditions': document['atomic_requirements'],
                             'outcomes': self._bindings.get('outcomes')}]
        else:
            if set(document) - {'g8son_version', 'file_id', 'gates', 'metadata'}:
                raise ValueError('unknown canonical G8SON root field')
            if document.get('g8son_version') != '1.0':
                raise ValueError('unsupported g8son_version')
            self._file_id = _text(document.get('file_id'), 'file_id')
            source_gates = document.get('gates')
        if not isinstance(source_gates, list) or not 1 <= len(source_gates) <= 3:
            raise ValueError('one to three gates required')
        if any(isinstance(g, dict) and 'order' in g for g in source_gates):
            orders = [g.get('order') if isinstance(g, dict) else None for g in source_gates]
            if (any(type(order) is not int or order < 1 for order in orders) or
                    len(set(orders)) != len(orders) or orders != sorted(orders)):
                raise ValueError('gate order must be complete, unique, positive and match source execution order')
        gate_ids = set()
        for gate in source_gates:
            if not isinstance(gate, dict):
                raise ValueError('gate must be an object')
            gate_id = _text(gate.get('gate_id'), 'gate_id')
            if gate_id in gate_ids:
                raise ValueError('duplicate gate_id: ' + gate_id)
            gate_ids.add(gate_id)
            operator = gate.get('type')
            if operator not in ('AND', 'OR', 'NAND', 'NOR'):
                raise ValueError('unsupported gate operator')
            _routes(gate.get('outcomes'))
            conditions = gate.get('conditions')
            if not isinstance(conditions, list) or not conditions:
                raise ValueError('nonempty conditions required')
            resolved = []
            req_ids = set()
            for index, authored in enumerate(conditions):
                identity = gate_id + ':' + str(index)
                if isinstance(authored, str):
                    _text(authored, 'requirement')
                    req_id, wording = identity, authored
                    condition = {}
                elif isinstance(authored, dict):
                    req_id = _text(authored.get('req_id', identity), 'req_id')
                    wording = authored.get('requirement', '')
                    if not isinstance(wording, str):
                        raise ValueError('requirement must be text')
                    condition = _copy(authored)
                    if historical:
                        _text(authored.get('req_id'), 'historical req_id')
                        _text(wording, 'historical requirement')
                else:
                    raise ValueError('condition must be text or object')
                if req_id in req_ids:
                    raise ValueError('duplicate requirement identity: ' + req_id)
                req_ids.add(req_id)
                key = req_id if historical else identity
                binding = requirements.get(key)
                if (isinstance(authored, str) or historical) and binding is None:
                    raise ValueError('explicit reviewed binding required: ' + key)
                if binding is not None:
                    if not isinstance(binding, dict):
                        raise ValueError('requirement binding must be an object')
                    if any(k in binding and binding[k] != v for k, v in
                           (('req_id', req_id), ('requirement', wording))):
                        raise ValueError('binding cannot replace source identity or wording')
                    if isinstance(authored, dict):
                        if any(k in authored and _digest(binding[k]) != _digest(authored[k]) for k in binding):
                            raise ValueError('binding cannot replace an authored condition field')
                        if 'path' in authored and 'evaluator_ref' in binding:
                            raise ValueError('binding cannot bypass an authored mechanical predicate')
                    condition.update(_copy(binding))
                condition['req_id'], condition['requirement'] = req_id, wording
                _validate_condition(condition)
                resolved.append(condition)
            self._gates.append({'gate_id': gate_id, 'operator': operator,
                                'conditions': resolved, 'outcomes': _copy(gate['outcomes'])})

    @property
    def document(self) -> dict:
        return _copy(self._document)

    @property
    def bindings(self) -> dict:
        return _copy(self._bindings)

    @property
    def fingerprint(self) -> str:
        return self._fingerprint

    def evaluate(self, context: dict, registry: Registry) -> dict:
        records, results = [], []
        for gate in self._gates:
            requirements, outcomes = [], []
            for condition in gate['conditions']:
                result = registry.evaluate(condition, context)
                outcomes.append(result.outcome)
                requirements.append({'req_id': condition['req_id'],
                                     'requirement': condition['requirement'],
                                     'outcome': _CANONICAL[result.outcome],
                                     'reason': result.reason, 'condition': _copy(condition),
                                     'evidence': _copy(result.evidence)})
            outcome = combine(gate['operator'], outcomes)
            results.append(outcome)
            canonical = _CANONICAL[outcome]
            records.append({'file_id': self._file_id, 'gate_id': gate['gate_id'],
                            'operator': gate['operator'], 'result': canonical,
                            'route': gate['outcomes'][canonical], 'requirements': requirements})
        return {'outcome': _CANONICAL[combine('AND', results)], 'gates': records}


def combine(operator: str, outcomes: list[Outcome]) -> Outcome:
    if operator not in ('AND', 'OR', 'NAND', 'NOR') or not outcomes:
        raise ValueError('nonempty inputs and supported operator required')
    if any(not isinstance(value, Outcome) for value in outcomes):
        raise ValueError('inputs must be Outcome values')
    if operator in ('AND', 'NAND'):
        result = (Outcome.FAIL if Outcome.FAIL in outcomes else
                  Outcome.PASS if all(x == Outcome.PASS for x in outcomes) else Outcome.UNKNOWN)
    else:
        result = (Outcome.PASS if Outcome.PASS in outcomes else
                  Outcome.FAIL if all(x == Outcome.FAIL for x in outcomes) else Outcome.UNKNOWN)
    if operator in ('NAND', 'NOR'):
        result = {Outcome.PASS: Outcome.FAIL, Outcome.FAIL: Outcome.PASS,
                  Outcome.UNKNOWN: Outcome.UNKNOWN}[result]
    return result
