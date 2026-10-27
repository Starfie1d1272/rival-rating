"""Generate a traceable post-hoc difference registry from frozen local inputs."""
import argparse
import json
import time
from pathlib import Path
from .differences import registry
from .integrity import sha256
from .heads import unique_object

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--domain',choices=['website','professional'],required=True)
    for name in ('report','batch','references','baseline'):
        parser.add_argument('--'+name,type=Path,required=True);parser.add_argument('--'+name+'-sha256',required=True)
    parser.add_argument('--identities',type=Path);parser.add_argument('--identities-sha256')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv); start=time.monotonic()
    try:
        files={name:getattr(args,name) for name in ('report','batch','references','baseline')}
        if args.identities: files['identities']=args.identities
        if args.output.exists() or args.output.resolve() in [v.resolve() for v in files.values()]: raise ValueError('output must be a new file')
        values={};hashes={}
        for name,path in files.items():
            expected=getattr(args,name+'_sha256'); actual=sha256(path)
            if expected!=actual:raise ValueError(name+' hash mismatch')
            hashes[name]=actual;values[name]=json.loads(path.read_text(),object_pairs_hook=unique_object)
        identities=None
        if args.domain=='website':
            if 'identities' not in values:raise ValueError('website identities required')
            identities={}
            for v in values['identities']:
                if set(v)!={'map','steam','season','userId'}:raise ValueError('invalid identity')
                key=(v['map'],v['steam'])
                if key in identities:raise ValueError('duplicate identity')
                identities[key]=(v['season'],v['userId'])
        rows=registry(args.domain,values['report'],values['batch'],values['references'],values['baseline'],identities)
        result={'schema':'rr-differences-v1','domain':args.domain,'inputSHA256':hashes,'elapsedSeconds':time.monotonic()-start,'records':rows,'limitations':['private reference mechanisms unknown','same-tick order unknown','HP snapshot conflicts unresolved','objective timing unresolved']}
        args.output.write_text(json.dumps(result,ensure_ascii=False,allow_nan=False,separators=(',',':'))+'\n')
        return 0
    except (OSError,ValueError,TypeError,KeyError) as e:
        print('error: '+str(e),file=__import__('sys').stderr);return 2
if __name__=='__main__':raise SystemExit(main())
