"""Resource-bound JSON loader for explicitly named local execution profiles.

GST uses a version-1 envelope with an explicit ``state`` object. Source paths
are relative to the manifest directory, including BONIT references in ORK.
Loaded properties return detached JSON values; start never reopens sources.
"""
from dataclasses import dataclass
import hashlib
import json
import math
import os
import re
import stat
from pathlib import Path

from .gates import GateSet


_POLICY_FIELDS = ('actors', 'writable_paths', 'max_attempts', 'max_seconds', 'max_commits', 'admissibility_ref')


@dataclass(frozen=True)
class LoadedUnit:
    _snapshot: str
    trace_path: Path

    def _get(self, key):
        return json.loads(self._snapshot)[key]

    @property
    def manifest(self):
        return self._get('manifest')

    @property
    def initial_state(self):
        return self._get('initial_state')

    @property
    def gate_documents(self):
        return self._get('gate_documents')

    @property
    def bindings(self):
        return self._get('bindings')

    @property
    def policy(self):
        return self._get('policy')

    @property
    def sources(self):
        """Manifest-relative source reference -> SHA256 of original bytes."""
        return self._get('sources')

    def start(self, runtime):
        policy = self.policy
        return runtime.create_run(self.initial_state, self.gate_documents,
                                  bindings=self.bindings,
                                  source_identity={'unit_id': self.manifest['unit_id'], 'resources': self.sources},
                                  **{key: policy[key] for key in _POLICY_FIELDS if key in policy})


def _text(value, label):
    if type(value) is not str or not value.strip():
        raise ValueError(label + ' must be nonempty text')


def _keys(document, required, optional, label):
    if not required <= document.keys() or document.keys() - required - optional:
        raise ValueError('unsupported ' + label + ' grammar: required/unknown keys')


def _json(raw, ref):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON key: ' + key)
            result[key] = value
        return result

    def number(text):
        value = float(text)
        if not math.isfinite(value):
            raise ValueError('nonfinite JSON number')
        return value

    def constant(text):
        raise ValueError('nonfinite JSON constant: ' + text)

    try:
        text = raw.decode('utf-8')
        # Bound nesting before the decoder allocates nested containers.
        depth, quoted, escaped = 0, False, False
        for char in text:
            if quoted:
                if escaped:
                    escaped = False
                elif char == '\\':
                    escaped = True
                elif char == '"':
                    quoted = False
            elif char == '"':
                quoted = True
            elif char in '[{':
                depth += 1
                if depth > 64:
                    raise ValueError('JSON depth exceeds 64')
            elif char in ']}':
                depth -= 1
        value = json.loads(text, object_pairs_hook=pairs, parse_float=number, parse_constant=constant)
        if type(value) is not dict:
            raise ValueError('JSON resource must be an object')
        return value
    except (ValueError, RecursionError) as exc:
        raise ValueError('invalid JSON in ' + ref + ': ' + str(exc)) from exc


def load_unit(path, *, max_resource_bytes=1_000_000):
    """Load without side effects. Maximum JSON container depth is 64.

    All refs are manifest-relative. Symlinks are deliberately unsupported even
    when their current target is inside the unit, avoiding path-swap races.
    """
    if type(max_resource_bytes) is not int or max_resource_bytes <= 0:
        raise ValueError('max_resource_bytes must be a positive integer')
    path = Path(path)
    root = path.parent.resolve()
    sources, claimed = {}, set()

    def resource(ref, suffix):
        _text(ref, 'resource reference')
        parts = ref.split('/')
        if (Path(ref).is_absolute() or any(p in ('', '.', '..') for p in parts)
                or '\\' in ref or '\x00' in ref or Path(ref).suffix != suffix):
            raise ValueError('unsafe reference or wrong suffix: ' + ref)
        if ref in claimed:
            raise ValueError('duplicate resource reference: ' + ref)
        claimed.add(ref)
        current = root
        for part in parts:
            current = current / part
            if current.is_symlink():
                raise ValueError('symlink resource is unsupported: ' + ref)
        return current

    def read(ref, suffix):
        resource(ref, suffix)
        # Walk using directory descriptors and NOFOLLOW: even a concurrent
        # replacement cannot turn a checked resource into an outside read.
        descriptors = []
        try:
            fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            descriptors.append(fd)
            parts = ref.split('/')
            for part in parts[:-1]:
                fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                descriptors.append(fd)
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            descriptors.append(fd)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > max_resource_bytes:
                raise ValueError('resource is not a regular file or exceeds byte limit: ' + ref)
            with os.fdopen(os.dup(fd), 'rb') as stream:
                raw = stream.read(max_resource_bytes + 1)
            if len(raw) > max_resource_bytes:
                raise ValueError('resource exceeds byte limit: ' + ref)
        except OSError as exc:
            raise ValueError('cannot safely read resource: ' + ref) from exc
        finally:
            for fd in reversed(descriptors):
                os.close(fd)
        document = _json(raw, ref)
        sources[ref] = hashlib.sha256(raw).hexdigest()
        return document

    manifest = read(path.name, '.mg8')
    _keys(manifest, {'mg8_version', 'unit_id', 'entry', 'state', 'gates', 'trace'}, {'metadata'}, 'MG8')
    if manifest['mg8_version'] != '1.0':
        raise ValueError('unsupported mg8_version')
    _text(manifest['unit_id'], 'unit_id')
    if type(manifest['state']) is not list or len(manifest['state']) != 1:
        raise ValueError('exactly one GST resource supported; multiple GST merge is unsupported')
    if type(manifest['gates']) is not list or not manifest['gates']:
        raise ValueError('nonempty gates resource list required')
    trace_path = resource(manifest['trace'], '.qson')
    ork = read(manifest['entry'], '.ork')
    _keys(ork, {'ork_profile', 'bonit', 'flow'}, set(), 'ORK JSON mg8-runtime-sequential/0.1')
    if ork['ork_profile'] != 'mg8-runtime-sequential/0.1':
        raise ValueError('unsupported ork_profile; only JSON mg8-runtime-sequential/0.1 supported')
    policy = read(ork['bonit'], '.bonit')
    _keys(policy, {'bonit_profile', 'actors', 'writable_paths', 'max_attempts', 'max_seconds', 'max_commits'},
          {'admissibility_ref', 'bindings'}, 'BONIT JSON mg8-runtime/0.1')
    if policy['bonit_profile'] != 'mg8-runtime/0.1':
        raise ValueError('unsupported bonit_profile')
    for key in ('actors', 'writable_paths'):
        values = policy[key]
        if type(values) is not list or not values:
            raise ValueError('nonempty ' + key + ' list required')
        for value in values:
            _text(value, key)
            if key == 'writable_paths' and (not value.startswith('/') or re.search(r'~(?![01])', value)):
                raise ValueError('writable_paths must contain JSON Pointers')
        if len(set(values)) != len(values):
            raise ValueError('duplicate ' + key)
    for key in ('max_attempts', 'max_commits'):
        if type(policy[key]) is not int or policy[key] <= 0:
            raise ValueError(key + ' must be a positive integer')
    seconds = policy['max_seconds']
    if type(seconds) not in (int, float) or seconds <= 0:
        raise ValueError('max_seconds must be positive and finite')
    if 'admissibility_ref' in policy:
        _text(policy['admissibility_ref'], 'admissibility_ref')
    registry = policy.get('bindings', {})
    if type(registry) is not dict or any(ref not in manifest['gates'] or type(binding) is not dict
                                          for ref, binding in registry.items()):
        raise ValueError('bindings must map declared gate resource refs to objects')
    state = read(manifest['state'][0], '.gst')
    if state.get('gst_version') != '1.0' or type(state.get('state')) is not dict:
        raise ValueError('GST requires gst_version 1.0 and an explicit state object')
    documents, bindings, gate_ids = [], [], []
    for ref in manifest['gates']:
        document = read(ref, '.g8son')
        binding = registry.get(ref, {})
        GateSet(document, binding)
        if 'atomic_requirements' in document:
            if ref not in registry:
                raise ValueError('historical G8SON requires explicit BONIT bindings')
            gate_ids.append(document['gate_id'])
        else:
            gate_ids.extend(gate['gate_id'] for gate in document['gates'])
        documents.append(document)
        bindings.append(binding)
    if len(set(gate_ids)) != len(gate_ids):
        raise ValueError('duplicate gate IDs across resources')
    if ork['flow'] != gate_ids:
        raise ValueError('ORK flow must cover every gate exactly in source execution order; no skips/repeats/reordering')
    snapshot = {'manifest': manifest, 'initial_state': state['state'],
                'gate_documents': documents, 'bindings': bindings,
                'policy': policy, 'sources': sources}
    return LoadedUnit(json.dumps(snapshot, allow_nan=False), trace_path)
