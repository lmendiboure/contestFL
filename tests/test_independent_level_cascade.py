import unittest
import hashlib
import sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from bench.smt import SparseMerkleMap
from review.independent_level_cascade import LevelCascadeAuditor, sha256

class TestIndependentCascade(unittest.TestCase):
    def setUp(self):
        self.ids=[sha256(b'a'),sha256(b'b')]
        self.updates=[np.array([1,2,3],dtype=np.int32),np.array([-1,0,1],dtype=np.int32)]
        self.hashes=[sha256(x.tobytes()) for x in self.updates]
        self.auditor=LevelCascadeAuditor(self.ids,self.updates,self.hashes,32)

    def snapshot(self, states):
        s,a,i=[SparseMerkleMap(32) for _ in range(3)]
        for cid,h,state in zip(self.ids,self.hashes,states):
            s.set(cid,h)
            if state>=2: a.set(cid,b'\x01')
            if state==3: i.set(cid,b'\x01')
        arr=[u for state,u in zip(states,self.updates) if state==3]
        if arr:
            z=np.sum(np.stack(arr),axis=0,dtype=np.int64)
            cp=sha256(b'ContestFL:canonical-aggregate'+len(arr).to_bytes(8,'big')+z.tobytes())
        else: cp=sha256(b'ContestFL:empty-checkpoint')
        return (s.root,a.root,i.root),cp

    def test_all_staged_faults(self):
        for states,wrong_cp,kind in (([1,3],False,'ADMIT'),([2,3],False,'INCLUDE'),
                                    ([3,3],True,'AGGREGATE'),([3,3],False,None)):
            roots,cp=self.snapshot(states)
            if wrong_cp:cp=sha256(cp+b'corrupt')
            audited=self.auditor.audit(states,roots,cp)
            self.assertEqual(audited.finding.kind if audited.finding else None,kind)
            self.assertEqual(audited.verified_keys,5)

    def test_no_future_leakage(self):
        roots,cp=self.snapshot([1,3]); finding=self.auditor.audit([1,3],roots,cp).finding
        self.assertEqual(finding.kind,'ADMIT')
        roots,cp=self.snapshot([2,3]); finding=self.auditor.audit([2,3],roots,cp).finding
        self.assertEqual(finding.kind,'INCLUDE')

    def test_reject_invalid_binding(self):
        roots,cp=self.snapshot([3,3])
        with self.assertRaises(ValueError):self.auditor.audit([3,3],[bytes(32),*roots[1:]],cp)
        with self.assertRaises(ValueError):self.auditor.audit([0,3],roots,cp)

    def test_commitment_mismatch(self):
        with self.assertRaises(ValueError): LevelCascadeAuditor(self.ids,self.updates,[bytes(32),self.hashes[1]],32)

if __name__=='__main__':unittest.main()
