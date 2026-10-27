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

def fold_evidence(package):
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
    for kind in ('HP','life','plant','defuse','enemyFlash','friendlyFlash'):
        for fold in routes:
            group=groups.get(kind+'/'+fold)
            if not group or not group.get('trainingGroups') or not group.get('validationGroups') or not set(group['trainingGroups']) <= routes[fold][0] or not set(group['validationGroups']) <= routes[fold][1]:
                raise ValueError('head and teacher fold mismatch')
    return {'routing':'verified_metadata', 'teacherFold':'verified_metadata', 'labelOrigin':'unverified', 'reason':'saved metadata alone does not prove teacher label origin'}
