"""Registers contract v3: the three knot columns of a todo row (done_when, updated_on, blocked_by). Synthetic fixtures only."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
import hashlib, tempfile, unittest
sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_integration as base
import test_aipm_light as lt
package=base.package;validate_package=base.validate_package;METHOD=base.METHOD
sys.path.insert(0,str(METHOD))
import light, ops

V2_SHA256='88dc258d6e7fc746c2e4ed66ffd08498369572bb319da2025be1364200e48ef4'   # registers_contract.yaml before the knot columns (version 2)

def row(**kw):return dict({'id':'D1','title':'合成','status':'todo','owner':'[unknown]'},**kw)

class Knot(unittest.TestCase):
    setUp=lt.Light.setUp;tearDown=lt.Light.tearDown;layer=lt.Light.layer;inp=lt.Light.inp
    def v2_layer(self,name='L2'):
        """A light Layer bound before the knot columns: build it while the latest contract is stood in by the frozen version 2."""
        real=package.registers_contract_path
        stand=lambda v=None:real(2 if v is None else v)
        package.registers_contract_path=stand;light.registers_contract_path=stand
        try:
            layer=self.layer(name);package.init(layer)
        finally:
            package.registers_contract_path=real;light.registers_contract_path=real
        return layer
    def check(self,layer,rows):
        base.write_yaml(layer/'Sheets/todo.yaml',{'todo':rows})
        r=validate_package.validate(layer/'Sheets',layer=layer)
        return r,[e['message'] for e in r['errors']],[w['message'] for w in r['warnings']]

    def test_a_v2_is_frozen_and_v2_layer_still_validates(self):
        self.assertEqual(hashlib.sha256((METHOD/'registers_contract.v2.yaml').read_bytes()).hexdigest(),V2_SHA256)
        self.assertEqual(package.registers_contract_path(2),METHOD/'registers_contract.v2.yaml')
        layer=self.v2_layer();saved=package.load(layer/'Sheets/format_contract.yaml')
        self.assertEqual((saved['registers_contract_version'],saved['registers_contract_sha256']),(2,V2_SHA256))
        r,e,w=self.check(layer,[row()]);self.assertTrue(r['pass'],e)      # no sha mismatch, no new check
        r,e,w=self.check(layer,[row(source='会議メモ')]);self.assertTrue(r['pass'],e);self.assertFalse(any('Documents/' in x for x in w))   # no source warning in v2

    def test_b_v3_without_knot_columns(self):
        layer=self.layer();package.init(layer)
        r,e,w=self.check(layer,[row(),row(id='D2',source='会議メモ')]);self.assertTrue(r['pass'],e)

    def test_c_v3_with_knot_columns(self):
        layer=self.layer();package.init(layer)
        r,e,w=self.check(layer,[row(source='T003',done_when='task_completed',updated_on='2026-11-04',blocked_by='L-1234-5-synth/T003'),
                                row(id='D2',source='Documents/memo.md',done_when='owner_action',blocked_by=['L-1234-5-synth/T003','L-1234-6-synth-SG1/T005']),
                                row(id='D3',done_when='external_event')])
        self.assertTrue(r['pass'],e)
        self.assertFalse(any('neither a backlog' in x for x in w))
        # an unquoted YAML date is a date object and is accepted
        (layer/'Sheets/todo.yaml').write_text('todo:\n- {id: D1, title: t, status: todo, owner: "[unknown]", updated_on: 2026-11-04}\n')
        self.assertTrue(validate_package.validate(layer/'Sheets',layer=layer)['pass'])

    def test_d_v3_bad_values_stop(self):
        layer=self.layer();package.init(layer)
        for bad in ({'done_when':'done'},{'done_when':['task_completed']},{'updated_on':'2026/11/04'},{'updated_on':'2026-13-40'},{'updated_on':'2026-11-4'},
                    {'blocked_by':'T003'},{'blocked_by':'L-1234-5-synth/3'},{'blocked_by':['L-1234-5-synth/T003','x']}):
            r,e,w=self.check(layer,[row(**bad)])
            self.assertFalse(r['pass'],bad);self.assertTrue(any(x['code']=='E_REGISTERS' for x in r['errors']),bad)

    def test_d2_source_outside_the_shapes_only_warns(self):
        layer=self.layer();package.init(layer)
        r,e,w=self.check(layer,[row(source='2026-10 の定例会議')]);self.assertTrue(r['pass'],e)
        self.assertTrue(any('neither a backlog' in x for x in w))

    def test_e_v2_new_columns_are_unknown_keys(self):
        layer=self.v2_layer('L2e')
        for k,v in (('done_when','task_completed'),('updated_on','2026-11-04'),('blocked_by','L-1/T1')):
            r,e,w=self.check(layer,[row(**{k:v})]);self.assertFalse(r['pass']);self.assertTrue(any('unknown key: '+k in x for x in e),e)

    def test_e2_ops_add_writes_columns_only_when_the_contract_has_them(self):
        l3=self.layer('L3');package.init(l3)
        out=ops.run(l3,'todo.add',self.inp(l3,'a.yaml',{'title':'足す','done_when':'owner_action','updated_on':'2026-11-04','blocked_by':'L-1234-5-synth/T003'}),apply=True)
        self.assertTrue(out['applied'])
        self.assertEqual(package.load(l3/'Sheets/todo.yaml')['todo'][0]['done_when'],'owner_action')
        with self.assertRaises(ValueError):ops.run(l3,'todo.add',self.inp(l3,'b.yaml',{'title':'悪い','done_when':'zzz'}),apply=True)
        self.assertEqual(len(package.load(l3/'Sheets/todo.yaml')['todo']),1)
        l2=self.v2_layer('L2o');before=(l2/'Sheets/todo.yaml').read_bytes()
        with self.assertRaises(ValueError) as cm:ops.run(l2,'todo.add',self.inp(l2,'c.yaml',{'title':'古い','done_when':'owner_action'}),apply=True)
        self.assertIn('古い版',str(cm.exception));self.assertEqual((l2/'Sheets/todo.yaml').read_bytes(),before)

    def test_e3_ops_link_updates_knot_columns_of_an_existing_row(self):
        l3=self.layer('L3l');package.init(l3)
        ops.run(l3,'todo.add',self.inp(l3,'a.yaml',{'title':'足す','source':'T001'}),apply=True)
        out=ops.run(l3,'todo.link',self.inp(l3,'b.yaml',{'id':'D1','updated_on':'2026-11-04','done_when':'task_completed'}),apply=True)
        self.assertTrue(out['applied'])
        got=package.load(l3/'Sheets/todo.yaml')['todo'][0]
        self.assertEqual((got['updated_on'],got['done_when'],got['source']),('2026-11-04','task_completed','T001'))
        before=(l3/'Sheets/todo.yaml').read_bytes()
        with self.assertRaises(ValueError):ops.run(l3,'todo.link',self.inp(l3,'c.yaml',{'id':'D1'}),apply=True)
        with self.assertRaises(ValueError):ops.run(l3,'todo.link',self.inp(l3,'d.yaml',{'id':'D1','updated_on':'2026/11/04'}),apply=True)
        self.assertEqual((l3/'Sheets/todo.yaml').read_bytes(),before)
        l2=self.v2_layer('L2l');ops.run(l2,'todo.add',self.inp(l2,'e.yaml',{'title':'古い'}),apply=True)
        before=(l2/'Sheets/todo.yaml').read_bytes()
        with self.assertRaises(ValueError) as cm:ops.run(l2,'todo.link',self.inp(l2,'f.yaml',{'id':'D1','updated_on':'2026-11-04'}),apply=True)
        self.assertIn('古い版',str(cm.exception));self.assertEqual((l2/'Sheets/todo.yaml').read_bytes(),before)

    def test_g_new_layer_is_latest(self):
        layer=self.layer('L3n');package.init(layer);saved=package.load(layer/'Sheets/format_contract.yaml')
        self.assertEqual(saved['registers_contract_version'],4);self.assertTrue(saved['version'].endswith('+registers.4'))
        self.assertEqual(saved['registers_contract_sha256'],base.sha(METHOD/'registers_contract.yaml'))
        latest=package.load(METHOD/'registers_contract.yaml');self.assertEqual((latest['version'],latest['contract_suffix']),(4,'+registers.4'))


class MoveWithDayAndNote(unittest.TestCase):
    """todo.move can write the closing day (updated_on) and one sentence of where it came from (note_add)."""
    setUp=lt.Light.setUp;tearDown=lt.Light.tearDown;layer=lt.Light.layer;inp=lt.Light.inp;v2_layer=Knot.v2_layer
    def rows(self,layer):return package.load(layer/'Sheets/todo.yaml')['todo']
    def test_writes_day_and_note_once(self):
        layer=self.layer();package.init(layer)
        base.write_yaml(layer/'Sheets/todo.yaml',{'todo':[row(note='合成のメモ。',updated_on='2026-10-01'),row(id='D2')]})
        ref=self.inp(layer,'m.yaml',{'id':'D1','status':'done','updated_on':'2026-11-06','note_add':'2026-11-06 本人の答えで閉じた（合成）'})
        trial=ops.run(layer,'todo.move',ref);self.assertFalse(trial['applied']);self.assertEqual(self.rows(layer)[0]['status'],'todo')
        r=ops.run(layer,'todo.move',ref,apply=True);self.assertTrue(r['applied'],r)
        d1=self.rows(layer)[0];self.assertEqual((d1['status'],str(d1['updated_on']),d1['note']),('done','2026-11-06','合成のメモ。 2026-11-06 本人の答えで閉じた（合成）'))
        ops.run(layer,'todo.move',ref,apply=True);self.assertEqual(self.rows(layer)[0]['note'],d1['note'])   # not added twice
        ops.run(layer,'todo.move',self.inp(layer,'m2.yaml',{'id':'D2','status':'cancelled','note_add':'要らない（合成）'}),apply=True)
        d2=self.rows(layer)[1];self.assertEqual((d2['status'],d2['note']),('cancelled','要らない（合成）'));self.assertNotIn('updated_on',d2)
    def test_status_only_is_as_before(self):
        layer=self.layer();package.init(layer)
        base.write_yaml(layer/'Sheets/todo.yaml',{'todo':[row(note='n',updated_on='2026-10-01')]})
        ops.run(layer,'todo.move',self.inp(layer,'m.yaml',{'id':'D1','status':'done'}),apply=True)
        d1=self.rows(layer)[0];self.assertEqual((d1['status'],d1['note'],str(d1['updated_on'])),('done','n','2026-10-01'))
    def test_bad_values_write_nothing(self):
        layer=self.layer();package.init(layer)
        base.write_yaml(layer/'Sheets/todo.yaml',{'todo':[row(note='n')]});before=(layer/'Sheets/todo.yaml').read_bytes()
        for bad in ({'updated_on':'2026/11/06'},{'updated_on':'2999-01-01'},{'note_add':'一行目\n二行目'},{'note_add':'x'*301},{'note_add':['a']}):
            with self.assertRaises(ValueError,msg=str(bad)):ops.run(layer,'todo.move',self.inp(layer,'b.yaml',dict({'id':'D1','status':'done'},**bad)),apply=True)
            self.assertEqual((layer/'Sheets/todo.yaml').read_bytes(),before)
    def test_v2_sheet_refuses_the_day_but_takes_the_note(self):
        layer=self.v2_layer();base.write_yaml(layer/'Sheets/todo.yaml',{'todo':[row()]})
        with self.assertRaisesRegex(ValueError,'古い版'):ops.run(layer,'todo.move',self.inp(layer,'m.yaml',{'id':'D1','status':'done','updated_on':'2026-11-06'}),apply=True)
        r=ops.run(layer,'todo.move',self.inp(layer,'n.yaml',{'id':'D1','status':'done','note_add':'合成'}),apply=True);self.assertTrue(r['applied'],r)
        self.assertEqual(self.rows(layer)[0]['note'],'合成')

if __name__=='__main__':unittest.main()
