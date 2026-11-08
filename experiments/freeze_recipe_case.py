"""Freeze a new prepared-role case before starting its own physics run."""
import argparse
import json


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('template');parser.add_argument('--bindings',required=True)
    parser.add_argument('--asset-lock',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args(argv)
    from simscene.recipes.cases import freeze_case_file
    result=freeze_case_file(args.template,args.bindings,args.asset_lock,args.output)
    print(json.dumps(result,indent=2));return 0


if __name__=='__main__':raise SystemExit(main())
