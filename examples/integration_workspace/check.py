"""Check one frozen positive/control pair for the fixed drawer workspace."""
import argparse
import json
from pathlib import Path

from simscene.verification.drawer_payload_pair import verify_pair


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--positive',required=True)
    parser.add_argument('--control',required=True)
    parser.add_argument('--case',required=True)
    parser.add_argument('--output',required=True,help='new report path; existing evidence is preserved')
    args=parser.parse_args()
    report=verify_pair(args.positive,args.control,args.case)
    with Path(args.output).open('x',encoding='utf8') as stream:
        json.dump(report,stream,ensure_ascii=False,indent=2,allow_nan=False);stream.write('\n')
    print(json.dumps({'passed':report['passed'],'output':args.output,'errors':report['errors']},ensure_ascii=False))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
