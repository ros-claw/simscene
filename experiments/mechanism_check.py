"""CLI compatibility entry point for the independent passive-mechanism checker."""
from simscene.verification.mechanism import *
from simscene.verification.mechanism import main

if __name__ == "__main__":
    raise SystemExit(main())
