"""Publication presentation only; all estimates and dispersions are supplied.

This module never reads experiment data or recomputes statistics.  In particular,
``run_sd`` is the original between-run standard deviation, not a confidence
interval.  Missing estimates are left empty and explicitly marked N/A.
"""
from contextlib import contextmanager
from functools import lru_cache
import math

import matplotlib as mpl
from matplotlib import font_manager
from matplotlib.text import Text
from matplotlib.ticker import FuncFormatter
import numpy as np


ALGORITHMS = ("Naive NDN", "VTDF", "RTVTDF", "TKAN-PDF")
COLORS = ("#808080", "#E69F00", "#009E73", "#8E5AA9")
HATCHES = ("", "///", "\\\\\\", "xx")
GROUP_WIDTH = .8


@lru_cache(maxsize=1)
def font_metadata():
    """Resolve an installed Times-like serif without silent sans substitution."""
    for family in ("Times New Roman", "Liberation Serif", "DejaVu Serif"):
        try:
            path = font_manager.findfont(font_manager.FontProperties(family=family),
                                         fallback_to_default=False)
        except ValueError:
            continue
        return {"requested_family": "Times New Roman", "selected_family": family,
                "path": path, "fallback": family != "Times New Roman"}
    raise RuntimeError("No supported serif font installed")


@contextmanager
def paper_style():
    """Temporarily apply the reference's serif, boxed axes and inward ticks."""
    font = font_metadata()
    with mpl.rc_context({
            "font.family": "serif", "font.serif": [font["selected_family"]],
            "font.size": 11, "axes.labelsize": 11, "axes.titlesize": 12,
            "axes.linewidth": .7, "axes.grid": False,
            "axes.spines.top": True, "axes.spines.right": True,
            "xtick.labelsize": 10, "ytick.labelsize": 10,
            "xtick.direction": "in", "ytick.direction": "in",
            "xtick.top": True, "ytick.right": True,
            "xtick.major.width": .7, "ytick.major.width": .7,
            "legend.fontsize": 9, "legend.frameon": True,
            "legend.fancybox": False, "legend.edgecolor": "black",
            "legend.framealpha": 1, "hatch.linewidth": .35,
            "errorbar.capsize": 2, "lines.linewidth": 1,
            "pdf.fonttype": 42, "ps.fonttype": 42, "svg.fonttype": "path",
            "savefig.dpi": 300, "savefig.facecolor": "white",
            "figure.facecolor": "white", "axes.facecolor": "white"}):
        yield dict(font)


def _number(value):
    if value is None:
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _label(value):
    if isinstance(value, (int, float)):
        return "{:g}".format(value)
    return str(value)


def _bars(ax, xlabels, points, slot, slots, color, hatch, label,
          group_width=GROUP_WIDTH, annotate_missing=True):
    if len(xlabels) != len(points):
        raise ValueError("One point is required for every group")
    if not (0 <= slot < slots) or slots < 1 or not 0 < group_width < 1:
        raise ValueError("Invalid categorical bar geometry")
    existing = getattr(ax, "_paper_xlabels", None)
    labels = [_label(value) for value in xlabels]
    if existing is not None and existing != labels:
        raise ValueError("All series on an axis must use identical categorical groups")
    values = []
    for point in points:
        mean, sd = _number(point.get("estimate")), _number(point.get("run_sd"))
        if sd is not None and sd < 0:
            raise ValueError("Standard deviation cannot be negative")
        values.append((mean, sd))
    width = group_width / slots
    positions = np.arange(len(labels), dtype=float) + (slot - (slots - 1) / 2) * width
    valid = [index for index, (mean, _) in enumerate(values) if mean is not None]
    missing = [index for index, (mean, _) in enumerate(values) if mean is None]
    bars = ax.bar([positions[index] for index in valid],
                  [values[index][0] for index in valid], width=width * .94,
                  color=color, edgecolor="black", linewidth=.55, hatch=hatch,
                  label=label, zorder=2)
    with_sd = [index for index in valid if values[index][1] is not None]
    errors = None
    if with_sd:
        errors = ax.errorbar([positions[index] for index in with_sd],
                            [values[index][0] for index in with_sd],
                            yerr=[values[index][1] for index in with_sd],
                            fmt="none", ecolor="black", elinewidth=.65,
                            capsize=2, capthick=.65, zorder=3)
    annotations = []
    if annotate_missing:
        for index in missing:
            annotations.append(ax.text(positions[index], .012, "N/A",
                                      transform=ax.get_xaxis_transform(),
                                      ha="center", va="bottom", rotation=90,
                                      color="black", fontsize=6.5))
    ax._paper_xlabels = labels
    finalize_axes(ax)
    return {"bars": bars, "errors": errors, "missing": annotations,
            "positions": positions, "valid_indices": valid,
            "missing_indices": missing}


def grouped_bars(ax, xlabels, series, *, group_width=GROUP_WIDTH,
                 annotate_missing=True):
    """Draw supplied point dictionaries as categorical, grouped bars.

    ``series`` is a sequence of ``{strategy: 0..3, points: [...], label?: ...}``.
    A mapping from strategy IDs to point lists is accepted too.  Supplying a
    strategy keeps its fixed color and slot among all four algorithms, including
    when only a subset is shown.  Non-algorithm series may instead supply
    ``label``, ``color`` and ``hatch``; these are spaced by their series count.
    Each point has ``estimate`` and optional ``run_sd``.  The result is a list of
    artist dictionaries, in the supplied series order.
    """
    if isinstance(series, dict):
        series = [{"strategy": key, "points": value} for key, value in series.items()]
    series = list(series)
    algorithm_series = bool(series) and all("strategy" in item for item in series)
    if any("strategy" in item for item in series) and not algorithm_series:
        raise ValueError("Do not mix algorithm and generic series on one axis")
    if algorithm_series:
        ids = [int(item["strategy"]) for item in series]
        if len(set(ids)) != len(ids) or any(index not in range(4) for index in ids):
            raise ValueError("Strategies must be unique IDs in 0..3")
    artists = []
    for ordinal, item in enumerate(series):
        index = int(item["strategy"]) if algorithm_series else ordinal
        color = COLORS[index] if algorithm_series else item.get("color", COLORS[index % 4])
        hatch = HATCHES[index] if algorithm_series else item.get("hatch", HATCHES[index % 4])
        label = ALGORITHMS[index] if algorithm_series else item["label"]
        artists.append(_bars(ax, xlabels, item["points"], index,
                             4 if algorithm_series else len(series), color, hatch,
                             label, group_width, annotate_missing))
    return artists


def draw_points(ax, xvalues, points, strategy, descriptive=False):
    """Adapter for plot_campaign._draw_points; uses original mean and run SD.

    ``descriptive`` is accepted for compatibility.  This restyling is explicitly
    a mean/SD presentation; it never substitutes existing confidence intervals
    for an absent SD.  Call finalize_axes after old callers overwrite xticks.
    """
    return grouped_bars(ax, xvalues, [{"strategy": strategy, "points": points}])[0]


def finalize_axes(ax):
    """Restore category ticks after legacy callers set numeric scan positions."""
    if getattr(ax, "name", "") == "3d":
        return
    labels = getattr(ax, "_paper_xlabels", None)
    if labels is not None:
        ax.set_xticks(np.arange(len(labels)))
        ax.set_xticklabels(labels)
        ax.set_xlim(-.6, len(labels) - .4)
    ax.grid(False, which="both")
    ax.tick_params(direction="in", top=True, right=True, width=.7)
    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_color("black")
        spine.set_linewidth(.7)


def display_name(value):
    """Replace the old algorithm's presentation name, leaving other text intact."""
    return (str(value).replace("Proposed (TKAN-LSTM)", "TKAN-PDF")
            .replace("Our proposed", "TKAN-PDF").replace("our proposed", "TKAN-PDF")
            .replace("Proposed", "TKAN-PDF"))


def style_figure(fig):
    """Apply final fonts/boxed axes and rename old display labels before export."""
    family = font_metadata()["selected_family"]
    for ax in fig.axes:
        finalize_axes(ax)
        # Text.set_text alone is overwritten by the formatter on the next draw,
        # including the strategy axis in legacy 3D plots.  Wrap only formatters
        # that actually expose the old name; numeric/scientific axes stay intact.
        for dimension in ("xaxis", "yaxis", "zaxis"):
            axis = getattr(ax, dimension, None)
            if axis is None:
                continue
            formatter = axis.get_major_formatter()
            if any(display_name(label.get_text()) != label.get_text()
                   for label in axis.get_majorticklabels()):
                axis.set_major_formatter(FuncFormatter(
                    lambda value, pos, original=formatter: display_name(original(value, pos))))
    for item in fig.findobj(match=Text):
        item.set_fontfamily(family)
        item.set_text(display_name(item.get_text()))
    for legend in fig.legends + [ax.get_legend() for ax in fig.axes if ax.get_legend()]:
        legend.set_frame_on(True)
        legend.get_frame().set_edgecolor("black")
        legend.get_frame().set_linewidth(.6)
        legend.get_frame().set_alpha(1)
    return fig
