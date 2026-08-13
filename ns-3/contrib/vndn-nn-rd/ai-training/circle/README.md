# Circle TKAN-LSTM training

This directory trains a serving-RSU classifier from the circle scenario's
`training-tag-<obu>.csv` files. The recurrent cell replaces the conventional
LSTM affine gate projection with a KAN B-spline projection (TKAN/KAN+LSTM).
All dataset, model and training code is contained in `train_tkan_lstm.py`.
`KANLinear` is imported from the shared open-source implementation at
`contrib/vndn-nn-rd/ai-training/efficient_kan/kan.py`; it is not reimplemented
in the circle training script.

## Data selection

The loader only uses runs whose `simulation-config.txt` contains the requested
`RsuForwardStrategy` (default: `NoForward`). RTT CSV files are ignored. Each
simulation/OBU file remains an independent time series, so a sequence never
crosses a run or vehicle boundary.

An OBU CSV is accepted only after its matching `training-tag-<obu>-stats.txt`
exists. This completion marker prevents a concurrent `run-vndn-circle.sh` run
from being read while it is still appending rows.

Complete runs, rather than overlapping windows, are assigned to training and
validation. Timesteps inside every window are always kept in their original
order. Shuffling training windows is valid because the model resets its hidden
state for each independent window; validation windows are not shuffled.

## Python 3.8 dependencies

From `~/ndnSIM/ns-3`:

```bash
python3.8 -m pip install --user --upgrade 'pip<25'
python3.8 -m pip install --user \
  -r contrib/vndn-nn-rd/ai-training/circle/requirements-python38.txt
```

The packages are installed in the Python 3.8 user site (normally
`~/.local/lib/python3.8/site-packages`) rather than inside the Git workspace.

## Train

The default input is `data/circle-simple/20260812`, with 100 epochs:

```bash
python3.8 contrib/vndn-nn-rd/ai-training/circle/train_tkan_lstm.py
```

To use another date directory:

```bash
python3.8 contrib/vndn-nn-rd/ai-training/circle/train_tkan_lstm.py \
  --data-root data/circle-simple/20260812 \
  --forward-strategy NoForward --epochs 100
```

Models are written to
`data/models/circle/tkan-lstm/YYYYMMDD-HHMMSS/`. The checkpoint filename also
contains `tkan-lstm`, `circle`, the forwarding strategy, and the full timestamp.
The directory additionally contains `training-history.csv` and
`training-summary.json`.
