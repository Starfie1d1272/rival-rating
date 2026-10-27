"""Run normalized offline round data, then optionally join external references."""
import argparse
import hashlib
import json
from pathlib import Path
from .heads import loads, unique_object
from .integrity import sha256
from .pipeline import MODES, score_round, replay_rich, aggregate, compare_after_scoring

def read_json(path):
    return json.loads(path.read_text(), object_pairs_hook=unique_object, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode',required=True,choices=MODES);p.add_argument('--input',required=True,type=Path)
    p.add_argument('--input-sha256',required=True);p.add_argument('--input-format',choices=['batch','inventory'],default='batch');p.add_argument('--parameters',required=True,type=Path)
    p.add_argument('--parameters-sha256',required=True);p.add_argument('--output',required=True,type=Path)
    p.add_argument('--identity-map',type=Path,help='Website map/player to season/user mapping, without reference scores')
    p.add_argument('--identity-sha256',help='Expected identity map hash')
    p.add_argument('--references',type=Path,help='Separate post-scoring JSON join input')
    a=p.parse_args(argv)
    try:
        inputs=[a.input.resolve(),a.parameters.resolve()]+([] if a.references is None else [a.references.resolve()])+([] if a.identity_map is None else [a.identity_map.resolve()])
        if a.output.resolve() in inputs or a.output.exists(): raise ValueError('output must be a new file, distinct from inputs')
        if sha256(a.input)!=a.input_sha256 or sha256(a.parameters)!=a.parameters_sha256: raise ValueError('input or parameter hash mismatch')
        package=loads(a.parameters.read_text())
        if a.mode=='professional_rich_diagnostic': ledgers=replay_rich(a.input,a.input_sha256)
        else:
            source=read_json(a.input)
            if a.input_format == 'inventory':
                from .adapters import adapt
                source=adapt(source,'website' if a.mode=='website_common_full' else 'professional')
            if source.get('schema')!='rr-offline-round-batch-v1' or not isinstance(source.get('rounds'),list) or not source['rounds']: raise ValueError('invalid or empty batch')
            ids=[item['round']['rid'] for item in source['rounds']]
            if len(ids)!=len(set(ids)): raise ValueError('duplicate round ID')
            ledgers=[score_round(package,a.mode,item['round'],item['events']) for item in source['rounds']]
        identities=None
        if a.mode=='website_common_full':
            if a.identity_map is None or a.identity_sha256 is None or sha256(a.identity_map)!=a.identity_sha256: raise ValueError('website identity map and matching hash required')
            entries=read_json(a.identity_map);identities={}
            for entry in entries:
                if set(entry)!={'map','steam','season','userId'}: raise ValueError('identity map must contain only map, steam, season, userId')
                key=(entry['map'],entry['steam'])
                if key in identities: raise ValueError('duplicate website identity mapping')
                identities[key]=(entry['season'],entry['userId'])
        result=aggregate(ledgers,identities)
        differences=None if a.references is None else compare_after_scoring(result,read_json(a.references))
        payload={'schema':'rr-offline-report-v1','mode':a.mode,'inputSHA256':a.input_sha256,'parameterSHA256':a.parameters_sha256,'identitySHA256':a.identity_sha256,'referenceSHA256':None if a.references is None else sha256(a.references),'ledgers':ledgers,'aggregates':result,'differences':differences,'limitations':['same-tick order unknown','HP snapshot conflicts unresolved','objective sensitivity unresolved','label origin unverified','external residual unexplained']}
        a.output.write_text(json.dumps(payload,ensure_ascii=False,allow_nan=False,indent=2)+'\n')
        return 0
    except (OSError,ValueError,TypeError,KeyError,OverflowError) as e:
        print('error: '+str(e),file=__import__('sys').stderr);return 2

if __name__=='__main__': raise SystemExit(main())
