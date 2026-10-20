#!/usr/bin/env python3.8
"""Validation-only uniform candidate probabilities; never a trained model."""
import argparse
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=5555)
    args = parser.parse_args(argv)
    from ns3gym import ns3env
    environment = ns3env.Ns3Env(port=args.port, startSim=False, debug=False)
    decisions = 0
    complete = False
    try:
        observation = environment.reset()
        while True:
            candidates = observation["rsu_ids"]
            if not len(candidates):
                raise ValueError("No candidate RSUs")
            action = [1.0 / len(candidates)] * len(candidates)
            observation, reward, done, info = environment.step(action)
            decisions += 1
            if done:
                complete = True
                break
    finally:
        environment.close()
    if not complete:
        return 1
    print("Done / 完成，共 {} 次决策 (validation-only uniform controller)".format(decisions))
    return 0


if __name__ == "__main__":
    sys.exit(main())
