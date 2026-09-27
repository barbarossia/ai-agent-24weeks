"""Enable ``python -m production_rag_lab`` in addition to the console script."""

from production_rag_lab.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
