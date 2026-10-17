import itertools
import unittest

from mg8_runtime.gates import Outcome, combine


class LogicTests(unittest.TestCase):
    def test_exhaustive_truth_tables(self):
        P, F, U = Outcome.PASS, Outcome.FAIL, Outcome.UNKNOWN
        table = [(P,P,P,P,F,F), (P,F,F,P,P,F), (P,U,U,P,U,F),
                 (F,P,F,P,P,F), (F,F,F,F,P,P), (F,U,F,U,P,U),
                 (U,P,U,P,U,F), (U,F,F,U,P,U), (U,U,U,U,U,U)]
        for a,b,*expected in table:
            for op, result in zip(('AND','OR','NAND','NOR'), expected):
                with self.subTest(op=op, a=a, b=b):
                    self.assertEqual(combine(op, [a,b]), result)
        for op, values in [('X',[P]), ('AND',[]), ('AND',['PASS'])]:
            with self.assertRaises(ValueError):
                combine(op, values)


class RegistryTests(unittest.TestCase):
    def test_registry_errors_and_fingerprint(self):
        from mg8_runtime.gates import Registry, Evaluation
        r = Registry()
        self.assertEqual(r.evaluate({'evaluator_ref':'missing'}, {}).outcome, Outcome.UNKNOWN)
        def good(ctx, condition):
            return Evaluation(Outcome.PASS, 'verified', {'ok':True})
        r.register('a', good)
        other = Registry()
        other.register('a', good)
        self.assertEqual(r.fingerprint(), other.fingerprint())
        with self.assertRaises(ValueError):
            r.register('a', good)
        self.assertEqual(r.evaluate({'evaluator_ref':'a'}, {}).outcome, Outcome.PASS)
        def broken(ctx, condition):
            raise RuntimeError('bad')
        r.register('broken', broken)
        r.register('invalid', lambda c,p: 'PASS')
        for ref in ['broken','invalid']:
            self.assertEqual(r.evaluate({'evaluator_ref':ref}, {}).outcome, Outcome.UNKNOWN)
        other = Registry()
        other.register('a', good, version='2')
        self.assertNotEqual(r.fingerprint(), other.fingerprint())

    def test_fingerprint_is_stable_across_hash_seeds(self):
        import os
        import subprocess
        import sys
        script = "from mg8_runtime.gates import Registry, Evaluation, Outcome\ndef check(c,p):\n return Evaluation(Outcome.PASS if c.get('x') in {'alpha','beta','gamma'} else Outcome.FAIL, 'ok')\nr=Registry(); r.register('check',check); print(r.fingerprint())"
        fingerprints=[]
        for seed in ['1','2','3']:
            fingerprints.append(subprocess.check_output([sys.executable,'-c',script],
                env=dict(os.environ,PYTHONHASHSEED=seed),text=True).strip())
        self.assertEqual(len(set(fingerprints)),1)

    def test_mechanical_values_paths_and_provenance(self):
        from mg8_runtime.gates import Registry
        r = Registry()
        ctx = {'current':{'n':1}, 'candidate':{'n':2,'flag':True},
               'evidence':{'a/b':{'~x':[3]}},
               '_provenance':{'/evidence/a~1b/~0x/0':'tool'}}
        p = {'path':'/evidence/a~1b/~0x/0','op':'gte','value':3,'evidence_kind':'tool'}
        self.assertEqual(r.evaluate(p,ctx).outcome, Outcome.PASS)
        self.assertEqual(r.evaluate(dict(p,evidence_kind='model'),ctx).outcome, Outcome.UNKNOWN)
        for op, expected in [('eq',False),('ne',True),('gt',True),('gte',True),('lt',False),('lte',False)]:
            self.assertEqual(r.evaluate({'path':'/candidate/n','op':op,'value':1},ctx).outcome,
                             Outcome.PASS if expected else Outcome.FAIL)
        for path, value in [('/candidate/flag',1),('/candidate/n','2'),('/candidate/no',1),('/candidate',1)]:
            self.assertEqual(r.evaluate({'path':path,'op':'eq','value':value},ctx).outcome, Outcome.UNKNOWN)
        for value in [float('nan'),float('inf'),{},[]]:
            self.assertEqual(r.evaluate({'path':'/candidate/n','op':'eq','value':value},ctx).outcome, Outcome.UNKNOWN)
        for path in ['/other/n','candidate/n','/candidate/~3','/evidence/a~1b/~0x/00']:
            self.assertEqual(r.evaluate({'path':path,'op':'eq','value':1},ctx).outcome, Outcome.UNKNOWN)

    def test_context_and_condition_isolation(self):
        from mg8_runtime.gates import Registry, Evaluation
        r = Registry()
        ctx = {'candidate':{'x':1}, '_provenance':{'/candidate/x':'model'}}
        condition = {'evaluator_ref':'mutator','requirement':'original'}
        def mutate(c,p):
            c['candidate']['x']=999
            c['_provenance']['/candidate/x']='tool'
            p['requirement']='changed'
            return Evaluation(Outcome.PASS,'ok',c)
        r.register('mutator',mutate)
        result = r.evaluate(condition,ctx)
        self.assertEqual(ctx['candidate']['x'],1)
        self.assertEqual(ctx['_provenance']['/candidate/x'],'model')
        self.assertEqual(condition['requirement'],'original')
        result.evidence['candidate']['x']=7
        self.assertEqual(ctx['candidate']['x'],1)


class GateSetTests(unittest.TestCase):
    def source(self, conditions=None):
        return {'g8son_version':'1.0','file_id':'source.file','gates':[
            {'gate_id':'verify','type':'AND','conditions':conditions or [
                {'path':'/candidate/n','op':'eq','value':1}],
             'outcomes':{'PASS':'commit','FAIL':'reject','INTERMEDIATE':'review'}}]}

    def test_source_identity_detachment_and_all_gates(self):
        from mg8_runtime.gates import GateSet, Registry
        source = self.source([{'req_id':'R1','requirement':'Exact wording!', 'evaluator_ref':'missing'}])
        other = self.source()['gates'][0]
        other['gate_id']='second'
        source['gates'].append(other)
        gates = GateSet(source)
        fingerprint = gates.fingerprint
        source['gates'][0]['conditions'][0]['requirement']='changed'
        gates.document['gates'].clear()
        gates.bindings['changed']=True
        result = gates.evaluate({'candidate':{'n':0}},Registry())
        self.assertEqual(result['outcome'],'FAIL')
        self.assertEqual(len(result['gates']),2)
        first = result['gates'][0]
        self.assertEqual(first['file_id'],'source.file')
        self.assertEqual(first['gate_id'],'verify')
        self.assertEqual(first['result'],'INTERMEDIATE')
        self.assertEqual(first['route'],'review')
        self.assertEqual(first['requirements'][0]['req_id'],'R1')
        self.assertEqual(first['requirements'][0]['requirement'],'Exact wording!')
        self.assertEqual(gates.fingerprint,fingerprint)
        self.assertNotIn('changed',gates.bindings)

    def test_strings_require_explicit_identity_binding(self):
        from mg8_runtime.gates import GateSet, Registry, Evaluation
        source = self.source(['Do not infer this requirement'])
        with self.assertRaises(ValueError):
            GateSet(source)
        bindings = {'requirements':{'verify:0':{'evaluator_ref':'reviewed'}}}
        gate = GateSet(source,bindings)
        bindings['requirements']['verify:0']['evaluator_ref']='missing'
        registry=Registry()
        registry.register('reviewed',lambda c,p: Evaluation(Outcome.PASS,'reviewed'))
        result=gate.evaluate({},registry)
        self.assertEqual(result['outcome'],'PASS')
        req=result['gates'][0]['requirements'][0]
        self.assertEqual(req['req_id'],'verify:0')
        self.assertEqual(req['requirement'],source['gates'][0]['conditions'][0])
        self.assertNotEqual(gate.fingerprint,GateSet(source,bindings).fingerprint)

    def test_historical_requires_reviewed_adapter(self):
        from mg8_runtime.gates import GateSet, Registry
        source={'gate_id':'old','atomic_requirements':[
            {'req_id':'R1','requirement':'If false repeat forever; consult GST'}]}
        with self.assertRaises(ValueError):
            GateSet(source)
        binding={'operator':'AND','requirements':{'R1':{'evaluator_ref':'human'}},
                 'outcomes':{'PASS':'commit','FAIL':'reject','INTERMEDIATE':'review'}}
        gate=GateSet(source,binding)
        result=gate.evaluate({},Registry())
        self.assertEqual(gate.document,source)
        self.assertEqual(result['outcome'],'INTERMEDIATE')
        self.assertEqual(result['gates'][0]['requirements'][0]['requirement'],
                         source['atomic_requirements'][0]['requirement'])
        with self.assertRaises(ValueError):
            GateSet(source,dict(binding,requirements={}))

    def test_unbound_object_requirement_is_unknown(self):
        from mg8_runtime.gates import GateSet, Registry
        gate=GateSet(self.source([{'req_id':'R1','requirement':'Needs review'}]))
        result=gate.evaluate({},Registry())
        self.assertEqual(result['outcome'],'INTERMEDIATE')
        self.assertIn('evaluator',result['gates'][0]['requirements'][0]['reason'])

    def test_no_short_circuit_and_independent_conditions(self):
        from mg8_runtime.gates import GateSet, Registry, Evaluation
        calls=[]
        r=Registry()
        def mutate(c,p):
            calls.append('mutate')
            c['candidate']['n']=999
            return Evaluation(Outcome.FAIL,'no')
        def observe(c,p):
            calls.append('observe')
            return Evaluation(Outcome.PASS if c['candidate']['n']==1 else Outcome.FAIL,'isolated')
        r.register('mutate',mutate)
        r.register('observe',observe)
        s=self.source([{'evaluator_ref':'mutate'},{'evaluator_ref':'observe'}])
        result=GateSet(s).evaluate({'candidate':{'n':1}},r)
        self.assertEqual(calls,['mutate','observe'])
        self.assertEqual(result['gates'][0]['requirements'][1]['outcome'],'PASS')
        for op, expected in [('AND','FAIL'),('OR','PASS'),('NAND','PASS'),('NOR','FAIL')]:
            s['gates'][0]['type']=op
            self.assertEqual(GateSet(s).evaluate({'candidate':{'n':1}},r)['outcome'],expected)

    def test_load_rejects_invalid_contracts(self):
        from mg8_runtime.gates import GateSet
        import copy
        bad=[]
        for version in ['2.0',1.0,None]:
            s=self.source(); s['g8son_version']=version; bad.append(s)
        for op in ['X','and',None]:
            s=self.source(); s['gates'][0]['type']=op; bad.append(s)
        for count in [0,4]:
            s=self.source(); s['gates']=[dict(s['gates'][0],gate_id=str(i)) for i in range(count)]; bad.append(s)
        s=self.source(); s['gates']*=2; bad.append(s)
        s=self.source(); s['gates'][0]['conditions']=[]; bad.append(s)
        for outcomes in [{'PASS':'commit'}, {'PASS':'anything','FAIL':'reject','INTERMEDIATE':'review'}]:
            s=self.source(); s['gates'][0]['outcomes']=outcomes; bad.append(s)
        for predicate in [ {'path':'/other/x','op':'eq','value':1},
                {'path':'/candidate/~x','op':'eq','value':1},
                {'path':'/candidate/x','op':'eval','value':1},
                {'path':'/candidate/x','op':'eq'},
                {'path':'/candidate/x','op':'eq','value':[]},
                {'path':'/candidate/x','op':'gt','value':True},
                {'path':'/candidate/x','op':'eq','value':float('inf')},
                {'evaluator_ref':''}]:
            bad.append(self.source([predicate]))
        s=self.source([{'req_id':'same','evaluator_ref':'a'},{'req_id':'same','evaluator_ref':'b'}]); bad.append(s)
        for source in bad:
            with self.subTest(source=source), self.assertRaises(ValueError):
                GateSet(source)
        for route in ['continue','commit','reject','stop','review','repeat']:
            s=self.source(); s['gates'][0]['outcomes']['PASS']=route
            GateSet(s)


if __name__ == '__main__':
    unittest.main()
