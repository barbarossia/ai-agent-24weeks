"""Default filesystem locations for the Week 10 lab.

Two distinct locations matter, and they are intentionally **not** the same:

* the **corpus** (the four Week 9 sample documents) lives in the Week 9 lab and is
  consumed read-only through the editable local path dependency, so Vector Only,
  BM25, and Hybrid provably run over the *same* Week 9 corpus and chunk objects;
* the **query set** (``data/eval_queries.jsonl``) is Week 10's own fixed, reviewed,
  gold-labeled evaluation set and therefore ships inside this package.
"""

from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
# parents: [0]=production_rag_lab, [1]=src, [2]=production-rag-lab,
#          [3]=week10, [4]=repository root
REPO_ROOT = PACKAGE_DIR.parents[3]
LAB_ROOT = PACKAGE_DIR.parents[1]

WEEK9_CORPUS_DIR = REPO_ROOT / "week9" / "vector-search-lab" / "data"
LOCAL_QUERIES_PATH = LAB_ROOT / "data" / "eval_queries.jsonl"


def get_default_data_dir() -> Path:
    """Return the read-only Week 9 corpus directory used by every method.

    Falls back to a local ``data`` directory so a copied/custom corpus can be used
    without touching this helper.
    """
    if WEEK9_CORPUS_DIR.is_dir():
        return WEEK9_CORPUS_DIR
    return LAB_ROOT / "data"


def get_default_queries_path() -> Path:
    """Return the bundled, fixed 24-row gold-labeled query set."""
    return LOCAL_QUERIES_PATH
