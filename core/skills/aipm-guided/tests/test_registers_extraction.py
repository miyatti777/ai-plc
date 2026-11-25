"""redit-extract reads a synthetic extraction draft with the same shape as a real one (sections TODO / WBS /
論点 / 仮説, header 案・区分・…・採否 or 本人の確定) and sorts its rows; judgements become judge / resolve drafts only; the AI writes
the redit input from the adopted rows; then redit → list → the person's (synthetic) reply → write goes through. Unsettled new
hypotheses are held. Synthetic content only."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
import unittest
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent));sys.path.insert(0,str(HERE))
import package, register_edits as rex
import test_init_and_reset as tr, test_integration as ti
import test_registers_edit as tre
write_yaml,sha=ti.write_yaml,ti.sha

DRAFT='''# synthetic extraction draft（合成）

## 0. 前提
- synthetic

## 1. TODO の案
| 案 | 区分 | 内容 | 出所 | 期限（案） | 採否 |
| --- | --- | --- | --- | --- | --- |
| S-T1 | 新規 | 合成の作業 A | Context/synthetic_memo.md | 2026-11-30 | **採用** |
| S-T2 | 重複（足さない） | 合成の作業 B | Context/synthetic_memo.md | - | 足さない案 |
| S-T3 | 新規 | 合成の作業 C | Context/synthetic_memo.md | - | **不採用** |
| S-T4 | 既存の更新（材料の追記だけ） | W2 の後で合成の作業 | Context/synthetic_memo.md | - | **採用** |
| S-T5 | 新規 | 合成の作業 E | Context/synthetic_memo.md | - | 採用しない |

## 2. WBS の案
| 案 | 区分 | 内容 | 出所 | 採否 |
| --- | --- | --- | --- | --- |
| S-W1 | 既存の更新（材料の追記だけ） W1 | 合成の証拠を足す | Context/synthetic_memo.md | **採用** |
| S-W2 | 新規 | 合成の成果物 | Context/synthetic_memo.md |  |
| S-W3 | 既存の更新（材料の追記だけ） MS1 | 合成の節目のメモ | Context/synthetic_memo.md | **採用** |
| S-W4 | 重複（足さない） | 合成の成果物 | Context/synthetic_memo.md | **採用**（MS1 の note に追記） |

## 3. 論点（issues）への影響の案
| 案 | 区分 | 論点 | 今日の材料（出所） | 影響 | 採否 |
| --- | --- | --- | --- | --- | --- |
| S-I1 | 既存の更新（材料の追記だけ） | I1: 合成の問い | Context/synthetic_memo.md | 材料が増える | **採用** |
| S-I2 | 既存の更新（判定案） | I1: 合成の問い | Context/synthetic_memo.md | 答えの案 | **採用** |
| S-I3 | 既存の更新（判定案） | I1: 合成の問い | Context/synthetic_memo.md | 答えの案 | **採用**（材料の追記だけ、判定は変えない） |

## 4. 仮説（hypotheses）への影響の案
| 案 | 区分 | 仮説 | 今日の材料（出所） | AI の案 | 本人の確定 |
| --- | --- | --- | --- | --- | --- |
| S-H1 | 既存の更新（判定案） | H1: 合成の仮説 | Context/synthetic_memo.md | supported の案 | **採用** |
| S-H2 | 新規（仮説の案） | 合成の新しい仮説（種類・基準は未定） | Context/synthetic_memo.md | - | **採用** |
| S-H3 | 判定に使えない | H1 | Context/synthetic_memo.md | - | 案を出さない |
| S-H4 | 既存の更新（材料の追記だけ） | H1: 合成の仮説 | Context/synthetic_memo.md | - | 採用 | 余計な列 |
| S-H5 | 既存の更新（判定案） | H1: 合成の仮説 | Context/synthetic_memo.md | 案 | **採用**（あとで見直す） |
| S-H6 | 既存の更新（材料の追記だけ） | **H2**: 合成の検証 | Context/synthetic_memo.md | - | **採用** |
| S-H7 | 既存の更新（判定案） | H1: 合成の仮説 | Context/synthetic_memo.md | 案 | **採用**（判定は supported、材料は別） |

## 5. 件数のまとめ
| 案 | 区分 | 件数 | 採否 |
| --- | --- | --- | --- |
| S-X1 | 新規 | 1 | **採用** |

## 8. 採否の記録（合成）
- 合成の記録
'''

class Extraction(tre.Base):
    def write_draft(self,layer,text=DRAFT,name='synthetic_extract.md'):
        (layer/'Documents').mkdir(exist_ok=True);(layer/'Documents'/name).write_text(text);return 'Documents/'+name
    def test_rows_are_sorted_and_nothing_is_written_on_dry_run(self):
        layer,root=self.box('ex');inp=self.write_draft(layer);ctx=tr.state(layer/'Context');box=tr.state(root)
        out=rex.extract(layer,inp);self.assertFalse(out['apply']);self.assertEqual(tr.state(layer/'Context'),ctx);self.assertEqual(tr.state(root),box)
        g={k:[r.get('case') for r in v] for k,v in out['groups'].items()}
        self.assertEqual(g['adopt_add_row'],['S-T1','S-H2']);self.assertEqual(g['adopt_append'],['S-W1','S-W3','S-I1','S-I3','S-H6'])   # S-H6: a bold id at the head   # S-I3: adopted with 「判定は変えない」 → material only
        self.assertEqual(g['needs_judgement'],['S-I2','S-H1']);self.assertEqual(g['rejected'],['S-T3','S-T5'])   # 「採用しない」 is not adopted
        self.assertEqual(g['conflict'],['S-W4']);self.assertEqual(g['adopted_with_note'],['S-H5','S-H7'])   # S-H7 names a judgement: not material   # a duplicate the person adopted; words added to the mark
        rows={r.get('case'):r for v in out['groups'].values() for r in v}
        self.assertEqual((rows['S-W3']['register'],rows['S-W3']['target']),('roadmap','MS1'));self.assertEqual(rows['S-I3']['note'],'材料の追記だけ、判定は変えない')
        self.assertEqual(g['skip'],['S-T2','S-H3'])   # a duplicate or 'not usable' row that was not adopted
        self.assertEqual(g['unmarked'],['S-W2'])
        self.assertEqual(g['unreadable'],['S-T4','S-H4','S-X1'])   # W2 in a TODO row, an extra cell, a table outside the sections: not guessed
        targets={r['case']:r.get('target') for v in out['groups'].values() for r in v if r.get('case')};self.assertEqual((targets['S-W1'],targets['S-I1'],targets['S-H1']),('W1','I1','H1'))
    def test_apply_writes_the_sorting_and_judge_drafts_only(self):
        layer,root=self.box('ap');inp=self.write_draft(layer);box=tr.state(root)
        out=rex.extract(layer,inp,apply=True);self.assertEqual(tr.state(root),box)   # registers untouched
        d=layer/'Context/aipm_changes'
        self.assertTrue((d/'rextract_synthetic_extract.yaml').is_file())
        jh=package.load(d/'judge_draft_case_S-H1.yaml');self.assertEqual(jh['input']['judgements'],[{'id':'H1','verdict':None}]);self.assertIsNone(jh['input']['judged_by']);self.assertEqual(jh['ai_proposal'],'supported の案')
        ji=package.load(d/'judge_draft_case_S-I2.yaml');self.assertEqual((ji['input']['id'],ji['input']['answer'],ji['input']['decided_by']),('I1',None,None))
        with self.assertRaisesRegex(ValueError,'already exists'):rex.extract(layer,inp,apply=True)   # never over an earlier file
    def test_an_unreadable_draft_stops(self):
        layer,root=self.box('ur');inp=self.write_draft(layer,'# no tables here\n\n- just text\n','bad.md')
        with self.assertRaisesRegex(ValueError,'no table'):rex.extract(layer,inp)
        inp=self.write_draft(layer,'## 1. TODO の案\n| 案 | 区分 | 内容 |\n| --- | --- | --- |\n| S-T1 | 新規 | x |\n','nodecision.md')
        with self.assertRaisesRegex(ValueError,'no table'):rex.extract(layer,inp)   # no decision column: unreadable only
    def test_from_draft_to_write(self):
        """extract → the AI writes the redit input from the adopted rows → redit (the unsettled new hypothesis is held) → list →
        the person's synthetic reply → write. The judgement rows never reach the registers."""
        layer,root=self.box('fw');out=rex.extract(layer,self.write_draft(layer),apply=True);g=out['groups']
        edits=[]
        for r in g['adopt_add_row']:
            if r['register']=='todo':edits.append({'op':'add_row','register':'todo','row_data':{'title':r['cells']['内容'],'owner':'[unknown]','due':r['cells']['期限（案）']},'reason':r['case']})
            if r['register']=='hypotheses':edits.append({'op':'add_row','register':'hypotheses','row_data':{'kind':'未定','claim':r['cells']['仮説'],'method':'未定','success':'未定','falsification':'未定'},'reason':r['case']})
        for r in g['adopt_append']:
            if r['register']=='roadmap':edits.append({'op':'append','register':'roadmap','row':r['target'],'field':'note','value':r['cells']['内容'],'reason':r['case']});continue
            field={'wbs':'evidence_refs','issues':'sources','hypotheses':'sources'}[r['register']]
            src=next(v for k,v in r['cells'].items() if '出所' in k)
            edits.append({'op':'append','register':r['register'],'row':r['target'],'field':field,'values':[src],'reason':r['case']})
        write_yaml(layer/'Context/aipm_changes/rinput_synthetic_extract.yaml',{'source':{'kind':'document','ref':'Documents/synthetic_extract.md（採否の記録は出どころ。承認ではない）'},'created_by':'ai','edits':edits})
        res=rex.redit(layer,'Context/aipm_changes/rinput_synthetic_extract.yaml',apply=True)
        self.assertEqual(len(res['proposals']),6);self.assertEqual([h['register'] for h in res['held']],['hypotheses'])   # the unsettled new hypothesis
        lst=rex.redit_list(layer);rex.redit_judge(layer,lst['digest'],'OK（全件反映）',tre.now(),'thread-synthetic')
        h_before=package.load(root/'hypotheses.yaml')
        rex.redit_apply(layer,apply=True,approval_ref='chat:synthetic')
        self.assertEqual(package.load(root/'todo.yaml')['todo'][-1]['title'],'合成の作業 A')
        self.assertIn('Context/synthetic_memo.md',package.load(root/'wbs.yaml')['wbs'][0]['evidence_refs'])
        self.assertIn('Context/synthetic_memo.md',package.load(root/'issues.yaml')['issues'][0]['sources'])
        h=package.load(root/'hypotheses.yaml');self.assertEqual([(x['id'],x['status']) for x in h['hypotheses']],[(x['id'],x['status']) for x in h_before['hypotheses']])   # no judgement, no new hypothesis
        i1=package.load(root/'issues.yaml')['issues'][0];self.assertEqual((i1['status'],i1.get('answer')),('open',None))
        self.assertEqual(self.final(layer,root)[:2],(True,[]))
    def test_cli(self):
        layer,root=self.box('cl');inp=self.write_draft(layer)
        code,out=tr.run_cli('redit-extract','--layer',str(layer),'--input',inp);self.assertEqual(code,0,out);self.assertFalse(out['apply'])

if __name__=='__main__':unittest.main()
