"""Integrity and fold metadata checks; hashes do not establish model correctness."""
import hashlib
import json
from pathlib import Path

def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def verify_files(root, manifest):
    root = Path(root).resolve()
    if not isinstance(manifest, dict) or not manifest: raise ValueError('empty integrity manifest')
    for name, expected in manifest.items():
        path = (root / name).resolve()
        if root not in path.parents or not isinstance(expected, str) or len(expected) != 64:
            raise ValueError('invalid integrity entry')
        if sha256(path) != expected: raise ValueError('hash mismatch: ' + name)
    return True

def fold_evidence(package, expected_universe=None):
    """Validate saved routing metadata; label provenance requires independent evidence."""
    folds = package.get('folds', {})
    teachers = folds.get('teacherOuter')
    groups = folds.get('headGroups')
    if not isinstance(teachers, list) or len(teachers) != 5 or not isinstance(groups, dict):
        return {'routing': 'unverified', 'teacherFold': 'unverified', 'labelOrigin': 'unverified'}
    routes = {}
    for t in teachers:
        fold = str(t['fold']); train=t['trainingGroups']; validation=t['validationGroups']
        if fold not in {'0','1','2','3','4'} or not train or not validation or len(set(train)) != len(train) or len(set(validation)) != len(validation) or set(train)&set(validation):
            raise ValueError('invalid teacher fold')
        if fold in routes: raise ValueError('duplicate teacher fold')
        routes[fold]=(set(train),set(validation))
    all_validation=[x for _,v in routes.values() for x in v]
    if len(all_validation)!=len(set(all_validation)): raise ValueError('validation route duplicated')
    universe=set(all_validation)
    if any(t|v != universe for t,v in routes.values()): raise ValueError('incomplete fold coverage')
    if expected_universe is not None:
        if not isinstance(expected_universe, (list,tuple)) or not expected_universe or len(set(expected_universe)) != len(expected_universe): raise ValueError('invalid independent universe')
        if set(expected_universe)!=universe: raise ValueError('independent universe coverage mismatch')
    for kind in ('HP','life','plant','defuse','enemyFlash','friendlyFlash'):
        full=groups.get(kind+'/full')
        if not full: raise ValueError('missing full head metadata')
        for label in ('trainingGroups','validationGroups'):
            values=full.get(label)
            if not isinstance(values,list) or len(set(values)) != len(values): raise ValueError('duplicate full head groups')
        for fold in routes:
            group=groups.get(kind+'/'+fold)
            if group:
                for label in ('trainingGroups','validationGroups'):
                    values=group.get(label)
                    if not isinstance(values,list) or len(set(values)) != len(values): raise ValueError('duplicate head groups')
            if not group or not group.get('trainingGroups') or not group.get('validationGroups') or not set(group['trainingGroups']) <= routes[fold][0] or not set(group['validationGroups']) <= routes[fold][1]:
                raise ValueError('head and teacher fold mismatch')
    return {'routing':'verified_against_independent_universe' if expected_universe is not None else 'internally_consistent', 'teacherFold':'internally_consistent', 'labelOrigin':'unverified', 'reason':'saved metadata alone does not prove complete universe or teacher label origin'}
