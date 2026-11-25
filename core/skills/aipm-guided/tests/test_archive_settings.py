"""where the archive copies go (.ai-plc/config.yaml, section aipm_archive). No file or no section keeps
the place as before (the Stock, under the Layer's primary business project read only from the Registry); business: none
does not open the Registry; where: layer keeps archive, register, apply and push inside the Layer (Documents/aipm_archive/).
Synthetic repository, Stock and Registry only; no real box is touched."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
import shutil, unittest
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent));sys.path.insert(0,str(HERE))
import package, validate_package, applying
import test_integration as ti, test_init_and_reset as tr
import test_archive_business as ab, test_apply_reflect_push as arp, test_apply_register_clone as arc
import registry_fixture as rf
write_yaml,sha=ti.write_yaml,ti.sha

def config(repo,**section):
    (repo/'.ai-plc').mkdir(exist_ok=True);write_yaml(repo/'.ai-plc/config.yaml',{'aipm_archive':section})

class ArchiveSettings(arc.Base):   # the helpers of arp.Apply, not its tests
    layer=ab.ArchiveUnderBusiness.layer
    persona_doc=arp.Apply.persona_doc;candidate=arp.Apply.candidate;confirmed_box=arp.Apply.confirmed_box
    judged=arp.Apply.judged;stock=arp.Apply.stock

    def test_no_config_keeps_the_business_path(self):
        layer,root,scope=self.layer('d')
        self.assertEqual(package.archive_settings(layer),{'where':'stock','business':'registry'})
        config(self.repo,other=1)   # a section without the keys: the same defaults
        self.assertEqual(package.archive_settings(layer),{'where':'stock','business':'registry'})
        res=package.archive_course(layer);self.assertTrue(res['pass'],res['errors'])
        t=package.load(root/'manifest.yaml')['archive_target']
        self.assertEqual((t['target_rel'],t['source']),('Stock/programs/Sample/projects/'+rf.BUSINESS+'/course_d','registry_read_only'))

    def test_auto_without_a_stock_is_layer_and_bad_values_stop(self):
        layer,root,scope=self.layer('a',link=False)
        shutil.rmtree(self.repo/'Stock');self.assertEqual(package.archive_settings(layer)['where'],'layer')
        config(self.repo);self.assertEqual(package.archive_settings(layer)['where'],'stock')   # a configured repository keeps stopping (review P2-1)
        with self.assertRaisesRegex(ValueError,'not found'):package.archive_course(layer)
        for bad in ({'where':'cloud'},{'business':'maybe'}):
            with self.subTest(bad=bad):
                config(self.repo,**bad)
                with self.assertRaisesRegex(ValueError,'aipm_archive'):package.archive_settings(layer)

    def test_business_none_does_not_open_the_registry(self):
        config(self.repo,business='none')
        layer,root,scope=self.layer('n',link=False);rf.db_path(self.repo).unlink()   # no Registry at all
        res=package.archive_course(layer);self.assertTrue(res['pass'],res['errors'])
        t=package.load(root/'manifest.yaml')['archive_target']
        self.assertEqual((t['target_rel'],t['source'],t['business_uid']),('Stock/programs/Sample/projects/course_n','config',''))
        m=package.load(root/'manifest.yaml')
        for r in m['records']:
            if r['archive_path']:self.assertEqual((self.repo/r['archive_path']).read_bytes(),(root/r['path']).read_bytes())
        self.assertTrue(validate_package.validate(root,phase='final',layer=layer)['pass'])
        config(self.repo,business='registry')   # a config-sourced Stock copy no longer passes once business is registry (review P2-2)
        self.assertIn('skips the business project',' '.join(e['message'] for e in validate_package.validate(root,phase='final',layer=layer)['errors']))
        # registry: the same Layer needs the Registry, and writes nothing without it
        layer2,root2,scope2=self.layer('r',link=False);stock=tr.state(self.repo/'Stock')
        with self.assertRaisesRegex(ValueError,'Registry not found'):package.archive_course(layer2)
        self.assertEqual(tr.state(self.repo/'Stock'),stock)

    def test_where_layer_archives_registers_applies_and_pushes_inside_the_layer(self):
        config(self.repo,where='layer');stock=self.stock()
        layer,root,target=self.confirmed_box('ly')
        self.assertEqual(target,'Documents/aipm_archive/course_ly');self.assertEqual(self.stock(),stock)   # the Stock is not touched
        self.assertTrue((layer/target/package.APPLY_LOG).is_file())
        m=package.load(root/'manifest.yaml');self.assertEqual(m['archive_target']['source'],'config')
        for r in m['records']:
            if r['archive_path']:
                self.assertTrue(r['archive_path'].startswith(target+'/documents/'))
                self.assertEqual((layer/r['archive_path']).read_bytes(),(root/r['path']).read_bytes())
        self.judged(layer,root)
        out=applying.apply(layer,apply=True,approval_ref='chat:synthetic apply');self.assertTrue(out['final']['pass'],out['final']['errors'])
        out=applying.push(layer,apply=True,approval_ref='chat:synthetic push');self.assertTrue(out['final']['pass'],out['final']['errors'])
        self.assertEqual([v['version'] for v in package.load(layer/target/package.APPLY_LOG)['versions']],[1,2])
        self.assertEqual(self.stock(),stock)
        with self.assertRaisesRegex(ValueError,'where is layer'):package.move_archive(layer)
        config(self.repo,where='stock')
        with self.assertRaisesRegex(ValueError,'copies are in the Layer'):package.move_archive(layer)   # review P3-3

    def test_where_layer_register_writes_the_log_in_the_layer(self):
        config(self.repo,where='layer')
        layer,root,scope=self.layer('g',link=False)
        res=package.archive_course(layer);self.assertTrue(res['pass'],res['errors'])
        m=package.load(root/'manifest.yaml');target=m['archive_target']['target_rel'];m.pop('applies');write_yaml(root/'manifest.yaml',m)
        (layer/target/package.APPLY_LOG).unlink()
        package.register(layer,apply=True,approval_ref='synthetic')
        self.assertEqual([v['kind'] for v in package.load(layer/target/package.APPLY_LOG)['versions']],['register'])
        self.assertTrue(validate_package.validate(root,phase='final',layer=layer)['pass'])

if __name__=='__main__':unittest.main()
