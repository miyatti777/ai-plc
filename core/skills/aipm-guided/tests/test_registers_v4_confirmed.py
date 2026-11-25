"""Registers contract v4: confirmed_on of a todo row . Synthetic fixtures only."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
import hashlib, unittest
sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_integration as base
import test_aipm_light as lt
import test_registers_v3_knot as k3
package=base.package;validate_package=base.validate_package;METHOD=base.METHOD
sys.path.insert(0,str(METHOD))
import light, ops, register_edits

V3_SHA256=hashlib.sha256((METHOD/'registers_contract.v3.yaml').read_bytes()).hexdigest()

def receipt(layer,**kw):
    d=package.load(layer/'intent.yaml')
    return dict({'kind':'user_reported','actor':'actual_user','decision':'confirm_todo_row','quote':'この行は正しい','received_at':'2026-11-04T14:32:00+09:00','scope_ids':[d['scope_id']],'rows':['D1']},**kw)

class Confirmed(unittest.TestCase):
    setUp=lt.Light.setUp;tearDown=lt.Light.tearDown;layer=lt.Light.layer;inp=lt.Light.inp;check=k3.Knot.check
    def latest(self,name='L4'):
        layer=self.layer(name);package.init(layer)
        ops.run(layer,'todo.add',self.inp(layer,'a.yaml',{'title':'足す'}),apply=True)
        return layer
    def pinned(self,version,name):
        real=package.registers_contract_path
        stand=lambda v=None:real(version if v is None else v)
        package.registers_contract_path=stand;light.registers_contract_path=stand
        try:
            layer=self.layer(name);package.init(layer)
        finally:
            package.registers_contract_path=real;light.registers_contract_path=real
        return layer

    def test_a_v3_is_frozen_and_keeps_working(self):
        self.assertEqual(package.registers_contract_path(3),METHOD/'registers_contract.v3.yaml')
        self.assertEqual(package.load(METHOD/'registers_contract.v3.yaml')['version'],3)
        layer=self.pinned(3,'L3');saved=package.load(layer/'Sheets/format_contract.yaml')
        self.assertEqual((saved['registers_contract_version'],saved['registers_contract_sha256']),(3,V3_SHA256))
        r,e,w=self.check(layer,[k3.row(done_when='owner_action')]);self.assertTrue(r['pass'],e)
        r,e,w=self.check(layer,[k3.row(confirmed_on='2026-11-04')]);self.assertFalse(r['pass']);self.assertTrue(any('unknown key: confirmed_on' in x for x in e),e)

    def test_b_values(self):
        layer=self.layer('L4v');package.init(layer)
        r,e,w=self.check(layer,[k3.row()]);self.assertTrue(r['pass'],e)
        r,e,w=self.check(layer,[k3.row(confirmed_on='2026-11-04')]);self.assertTrue(r['pass'],e)
        for bad in ('2026/11/04','2026-13-40','昨日'):
            r,e,w=self.check(layer,[k3.row(confirmed_on=bad)]);self.assertFalse(r['pass'],bad);self.assertTrue(any('confirmed_on' in x for x in e),e)

    def test_c_link_writes_with_the_owners_answer_and_keeps_the_record(self):
        layer=self.latest()
        tried=ops.run(layer,'todo.link',self.inp(layer,'t.yaml',{'id':'D1','confirmed_on':'2026-11-04','receipt':receipt(layer)}))
        self.assertFalse(tried['applied']);self.assertFalse((layer/ops.CONFIRMATIONS).exists())
        out=ops.run(layer,'todo.link',self.inp(layer,'b.yaml',{'id':'D1','confirmed_on':'2026-11-04','receipt':receipt(layer)}),apply=True)
        self.assertTrue(out['applied'])
        self.assertEqual(package.load(layer/'Sheets/todo.yaml')['todo'][0]['confirmed_on'],'2026-11-04')
        rec=package.load(layer/ops.CONFIRMATIONS)['confirmations'][0]
        self.assertEqual((rec['row'],rec['confirmed_on'],rec['actor'],rec['quote']),('D1','2026-11-04','actual_user','この行は正しい'))
        self.assertTrue(validate_package.validate(layer/'Sheets',layer=layer)['pass'])

    def test_d_link_without_a_proper_answer_writes_nothing(self):
        layer=self.latest();before=(layer/'Sheets/todo.yaml').read_bytes()
        future=ops.run(layer,'check')   # the layer is readable before the refusals below
        self.assertEqual(future['route'],'selected')
        with self.assertRaises(ValueError):ops.run(layer,'todo.link',self.inp(layer,'f.yaml',{'id':'D1','confirmed_on':'2099-01-01','receipt':receipt(layer,received_at='2099-01-01T10:00:00+09:00')}),apply=True)
        bads=[None,receipt(layer,actor='ai'),receipt(layer,kind='ai'),receipt(layer,decision='accept_named_rows'),receipt(layer,quote=' '),receipt(layer,received_at=None),
              receipt(layer,scope_ids=['L-other']),receipt(layer,rows=['D2']),receipt(layer,rows=['D1','D2']),receipt(layer,received_at='2026-11-03T10:00:00+09:00')]
        for i,bad in enumerate(bads):
            inp={'id':'D1','confirmed_on':'2026-11-04'}
            if bad is not None:inp['receipt']=bad
            with self.assertRaises(ValueError):ops.run(layer,'todo.link',self.inp(layer,f'x{i}.yaml',inp),apply=True)
        with self.assertRaises(ValueError):ops.run(layer,'todo.link',self.inp(layer,'y.yaml',{'id':'D1','updated_on':'2026-11-04','receipt':receipt(layer)}),apply=True)
        self.assertEqual((layer/'Sheets/todo.yaml').read_bytes(),before);self.assertFalse((layer/ops.CONFIRMATIONS).exists())

    def test_e_old_version_stops(self):
        layer=self.pinned(3,'L3o');ops.run(layer,'todo.add',self.inp(layer,'a.yaml',{'title':'古い'}),apply=True)
        before=(layer/'Sheets/todo.yaml').read_bytes()
        with self.assertRaises(ValueError) as cm:ops.run(layer,'todo.link',self.inp(layer,'b.yaml',{'id':'D1','confirmed_on':'2026-11-04','receipt':receipt(layer)}),apply=True)
        self.assertIn('古い版',str(cm.exception));self.assertEqual((layer/'Sheets/todo.yaml').read_bytes(),before)
        v2=self.pinned(2,'L2o')
        r,e,w=self.check(v2,[k3.row(confirmed_on='2026-11-04')]);self.assertFalse(r['pass']);self.assertTrue(any('unknown key: confirmed_on' in x for x in e),e)

    def test_e2_bad_record_file_stops_before_the_row_is_written(self):
        layer=self.latest();before=(layer/'Sheets/todo.yaml').read_bytes()
        (layer/'Context').mkdir(exist_ok=True);(layer/ops.CONFIRMATIONS).write_text('confirmations: 5\n',encoding='utf-8')
        with self.assertRaises(ValueError):ops.run(layer,'todo.link',self.inp(layer,'g.yaml',{'id':'D1','confirmed_on':'2026-11-04','receipt':receipt(layer)}),apply=True)
        self.assertEqual((layer/'Sheets/todo.yaml').read_bytes(),before)

    def test_f_other_doors_never_write_it(self):
        layer=self.latest()
        with self.assertRaises(ValueError):ops.run(layer,'todo.add',self.inp(layer,'c.yaml',{'title':'足す','confirmed_on':'2026-11-04'}),apply=True)
        src=(METHOD/'register_edits.py').read_text(encoding='utf-8')
        self.assertIn("a new row never carries it",src)

if __name__=='__main__':unittest.main()
