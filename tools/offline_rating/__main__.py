"""Explicit file-I/O boundary for the optional offline audit tools."""

import argparse
import json
from pathlib import Path
import sys

from .export_parameters import export_json
from .heads import infer, loads
from .integrity import verify_files, fold_evidence, sha256


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    validate = sub.add_parser('validate', help='Validate a strict JSON package')
    validate.add_argument('input', type=Path)
    export = sub.add_parser('export', help='Export validated JSON without refitting')
    export.add_argument('input', type=Path)
    export.add_argument('output', type=Path)
    predict = sub.add_parser('predict', help='Infer one synthetic or supplied feature vector')
    predict.add_argument('input', type=Path)
    predict.add_argument('--kind', required=True)
    predict.add_argument('--fold', default='full')
    predict.add_argument('--map', dest='map_name', required=True)
    predict.add_argument('--features', required=True, help='Ordered JSON array')
    predict.add_argument('--input-sha256', required=True, help='Expected SHA256 of input parameter file')
    predict.add_argument('--dose', default='1', help='Number, or enemy-flash array')
    check = sub.add_parser('integrity', help='Verify frozen files against a manifest')
    check.add_argument('root', type=Path)
    check.add_argument('manifest', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'integrity':
            manifest = json.loads(args.manifest.read_text(encoding='utf-8'), object_pairs_hook=__import__('tools.offline_rating.heads', fromlist=['unique_object']).unique_object)
            verify_files(args.root, manifest)
            print(json.dumps({'integrity': 'verified'}))
            return 0
        if args.command == 'predict' and sha256(args.input) != args.input_sha256:
            raise ValueError('input parameter hash mismatch')
        package = loads(args.input.read_text(encoding='utf-8'))
        if args.command == 'validate':
            print(json.dumps({'schema': package['schema'], 'heads': len(package['heads']), 'foldEvidence': fold_evidence(package)}))
        elif args.command == 'export':
            text = export_json(package)
            args.output.write_text(text, encoding='utf-8')
        else:
            value = infer(package, args.kind, args.fold,
                          json.loads(args.features), args.map_name, json.loads(args.dose))
            print(json.dumps({'value': value}, allow_nan=False))
    except (ValueError, TypeError, KeyError, OSError, OverflowError) as error:
        print('error: ' + str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
