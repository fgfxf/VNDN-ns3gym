#!/usr/bin/env python3.8
"""Build hashed, causally labelled hello-window shards from a frozen source list."""
import argparse
from pathlib import Path
import sys

AI_ROOT = Path(__file__).resolve().parents[2] / "contrib/vndn-nn-rd/ai-training"
sys.path.insert(0, str(AI_ROOT))
from formal_data import build_dataset  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    result = build_dataset(args.sources, args.output_dir)
    print("Dataset: {}".format(args.output_dir / "dataset-manifest.json"))
    print("Samples: {}".format({key: value["sample_count"]
                               for key, value in result["splits"].items()}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
