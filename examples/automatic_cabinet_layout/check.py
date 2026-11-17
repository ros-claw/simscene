"""Check the frozen cabinet layout case and its additional physical evidence."""
import argparse
import json
from pathlib import Path

from simscene.verification.automatic_cabinet_layout import verify as verify_example


def verify(run):
    return verify_example(run, Path(__file__).resolve().parent)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    parser.add_argument('--output', required=True, help='new JSON report path')
    args = parser.parse_args()
    report = verify(args.run)
    with Path(args.output).open('x', encoding='utf8') as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'passed': report['passed'], 'output': args.output}, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
