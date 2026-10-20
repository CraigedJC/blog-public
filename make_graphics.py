#!/usr/bin/env python3
"""Renders the three blog graphics (1600x900 PNG). Palette and ink follow the dataviz reference."""
import json
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle

HERE = Path(__file__).parent
OUT = HERE / "graphics"
OUT.mkdir(exist_ok=True)

SURFACE, INK, INK2, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
BLUE, ORANGE, AQUA, VIOLET = "#2a78d6", "#eb6834", "#1baf7a", "#6250d6"
BLUES = ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281"]  # ordinal ramp, steps 250 to 650
plt.rcParams["font.family"] = "DejaVu Sans"


def tint(hex_color, amount=0.86):
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    mix = lambda c: int(c + (255 - c) * amount)
    return "#%02x%02x%02x" % (mix(r), mix(g), mix(b))


def canvas():
    fig = plt.figure(figsize=(16, 9), dpi=100, facecolor=SURFACE)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 9)
    ax.axis("off")
    return fig, ax


def header(ax, title, sub):
    ax.text(0.75, 8.35, title, fontsize=28, fontweight="bold", color=INK, va="center")
    ax.text(0.75, 7.75, sub, fontsize=14, color=INK2, va="center")
    ax.text(15.25, 0.3, "blog.chiffers.com", fontsize=11, color=MUTED, ha="right", va="center")


# ---------------------------------------------------------------- 1. the ladder
def ladder():
    fig, ax = canvas()
    header(ax, "The ladder, not the leap",
           "Each rung hands the agent more authority. Each one is earned with data from the rung below.")
    rungs = [
        ("Agent as a step", "Workflow decides what happens next", "Hard gate on every run"),
        ("Bounded autonomy", "Workflow sequences, agent picks its tools", "Schemas, assertions, a model as judge"),
        ("Agent plans", "Agent proposes, a human approves", "Plan reviewed before it runs"),
        ("Agent executes", "Agent runs end to end inside policy", "Sampled audits, hard gates on irreversible actions"),
        ("Self improving", "System proposes changes to itself", "Eval suite gates every promotion"),
    ]
    w, gap, x0, base = 2.7, 0.25, 0.75, 2.95
    for i, (name, control, verify) in enumerate(rungs):
        x = x0 + i * (w + gap)
        h = 0.9 + i * 0.6
        ax.add_patch(Rectangle((x, base), w, h, facecolor=BLUES[i], edgecolor="none"))
        ax.text(x + w / 2, base + h / 2, str(i + 1), fontsize=34, fontweight="bold",
                color=INK if i < 2 else "white", ha="center", va="center")
        ax.text(x + w / 2, base + h + 0.25, name, fontsize=14.5, fontweight="bold", color=INK,
                ha="center", va="bottom")
        ax.text(x, 2.6, "CONTROL", fontsize=9, color=MUTED, fontweight="bold", va="center")
        ax.text(x, 2.4, "\n".join(textwrap.wrap(control, 27)), fontsize=11.5, color=INK, va="top", linespacing=1.3)
        ax.text(x, 1.65, "VERIFICATION", fontsize=9, color=MUTED, fontweight="bold", va="center")
        ax.text(x, 1.45, "\n".join(textwrap.wrap(verify, 27)), fontsize=11.5, color=INK, va="top", linespacing=1.3)
    ax.plot([x0, 15.25], [base, base], color=INK2, linewidth=1.2)
    ax.add_patch(FancyArrowPatch((x0, 7.15), (15.25, 7.15), arrowstyle="-|>", mutation_scale=18,
                                 color=INK2, linewidth=1.6))
    ax.text(8, 7.35, "Authority moves from the workflow to the agent", fontsize=12.5, color=INK2,
            ha="center", va="bottom")
    ax.text(0.75, 0.3, "Some workflows should stop at rung 2 and stay there. That is architecture, not failure.",
            fontsize=12, color=INK2, style="italic", va="center")
    fig.savefig(OUT / "1-ladder.png", facecolor=SURFACE)
    plt.close(fig)


# ---------------------------------------------------------------- 2. the Logic App flow
def flow():
    fig, ax = canvas()
    header(ax, "Inside the Logic App demo",
           "An actor agent, an independent audit, a human gate and a ratchet that moves the sample rate.")
    bw, bh, x0, step = 2.4, 1.75, 0.8, 3.0
    cx = lambda i: x0 + i * step + bw / 2
    row1, row2 = 5.7, 2.8  # centre y

    def box(i, cy, title, sub, color):
        x = x0 + i * step
        ax.add_patch(FancyBboxPatch((x, cy - bh / 2), bw, bh, boxstyle="round,pad=0.02,rounding_size=0.12",
                                    facecolor=tint(color), edgecolor=color, linewidth=2))
        ax.text(x + bw / 2, cy + 0.5, title, fontsize=13, fontweight="bold", color=INK, ha="center", va="center")
        ax.text(x + bw / 2, cy + 0.2, "\n".join(textwrap.wrap(sub, 28)), fontsize=9.5, color=INK2,
                ha="center", va="top", linespacing=1.3)

    top = [
        ("1  Trigger", "HTTP request with the task and its action class", BLUE),
        ("2  Read state", "Autonomy mode and sample rate from Table Storage", BLUE),
        ("3  Kill switch", "Stop the run if the switch is on", BLUE),
        ("4  Actor agent", "Azure OpenAI deployment A, system identity", BLUE),
        ("5  Audit needed?", "Gated: always. Sampled: a random slice. Irreversible or low confidence: always", BLUE),
    ]
    bottom = [  # drawn right to left, so index 4 sits under box 5
        (4, "6  Auditor", "Independent: a different model and a different identity from the actor", ORANGE),
        (3, "7  Policy gate", "Irreversible, low confidence or a failed audit goes to a human", AQUA),
        (2, "8  Human or execute", "Teams escalation, or run the action", AQUA),
        (1, "9  Autonomy ratchet", "Promote, hold or demote the sample rate", BLUE),
        (0, "10  Persist", "Write state and the audit log, then respond", BLUE),
    ]
    for i, (t, s, c) in enumerate(top):
        box(i, row1, t, s, c)
    for i, t, s, c in bottom:
        box(i, row2, t, s, c)

    def arrow(p, q, style="-|>", ls="-", rad=0.0):
        ax.add_patch(FancyArrowPatch(p, q, arrowstyle=style, mutation_scale=16, color=INK2, linewidth=1.6,
                                     linestyle=ls, connectionstyle=f"arc3,rad={rad}"))

    for i in range(4):  # top row, left to right
        arrow((x0 + i * step + bw + 0.03, row1), (x0 + (i + 1) * step - 0.03, row1))
    arrow((cx(4), row1 - bh / 2 - 0.03), (cx(4), row2 + bh / 2 + 0.03))  # 5 to 6
    for i in (4, 3, 2, 1):  # bottom row, right to left
        arrow((x0 + i * step - 0.03, row2), (x0 + (i - 1) * step + bw + 0.03, row2))
    # not sampled: skip the auditor
    arrow((x0 + 4 * step + 0.3, row1 - bh / 2 - 0.03), (x0 + 3 * step + bw - 0.2, row2 + bh / 2 + 0.03),
          ls=(0, (5, 4)), rad=0.0)
    ax.text(10.35, 4.1, "not sampled: skip the audit", fontsize=10, color=INK2,
            ha="center", va="center", style="italic",
            bbox=dict(facecolor=SURFACE, edgecolor="none", pad=2))

    # legend: identity is never colour alone, so each swatch is labelled
    lx, ly = 0.8, 1.0
    for j, (c, label) in enumerate([(BLUE, "Workflow step"), (ORANGE, "Independent audit"),
                                    (AQUA, "Human gate")]):
        xx = lx + j * 3.3
        ax.add_patch(Rectangle((xx, ly - 0.14), 0.32, 0.28, facecolor=tint(c), edgecolor=c, linewidth=2))
        ax.text(xx + 0.45, ly, label, fontsize=11.5, color=INK, va="center")
    ax.text(0.8, 0.45, "Concurrency is set to 1 run at a time because the ratchet updates a single state row.",
            fontsize=10.5, color=MUTED, va="center")
    fig.savefig(OUT / "2-logic-app-flow.png", facecolor=SURFACE)
    plt.close(fig)


# ---------------------------------------------------------------- 3. the ratchet in action
def ratchet():
    d = json.loads((HERE / "ratchet_sim.json").read_text())
    s, runs = d["series"], d["runs"]
    drift0, drift1 = d["drift_start"], d["drift_end"]
    demote = next(e for e in d["events"] if e["decision"] == "demote" and e["run"] >= drift0)
    bad_during = demote["slipped_so_far"] - d["slipped_at_drift_start"]

    fig = plt.figure(figsize=(16, 9), dpi=100, facecolor=SURFACE)
    fig.text(0.047, 0.925, "The ratchet in action (simulation)", fontsize=28, fontweight="bold", color=INK, va="center")
    fig.text(0.047, 0.868, "Share of runs that get an independent audit. It halves as trust is earned and snaps back to 100% on drift.",
             fontsize=14, color=INK2, va="center")
    ax = fig.add_axes([0.075, 0.2, 0.89, 0.56], facecolor=SURFACE)
    xs = list(range(1, runs + 1))
    ax.axvspan(drift0, drift1, color=tint(ORANGE, 0.82), lw=0)
    from matplotlib.ticker import FuncFormatter
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f'{int(v):,}'))
    ax.step(xs, s, where="post", color=BLUE, linewidth=2.2)
    ax.set_xlim(0, runs)
    ax.set_ylim(0, 128)
    ax.set_yticks([0, 25, 50, 75, 100])
    ax.set_yticklabels(["0%", "25%", "50%", "75%", "100%"], color=MUTED, fontsize=11)
    ax.tick_params(axis="x", colors=MUTED, labelsize=11, length=0)
    ax.tick_params(axis="y", length=0)
    ax.set_xlabel("Workflow runs", color=INK2, fontsize=12, labelpad=10)
    ax.grid(axis="y", color=GRID, linewidth=1)
    ax.axhline(5, color=MUTED, linewidth=1, linestyle=(0, (4, 4)))
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.spines["bottom"].set_color("#c3c2b7")

    ax.text(2000, 9, "5% floor: the lowest audit rate this workflow is allowed", fontsize=11, color=INK2, va="bottom")
    ax.text(drift0 + (drift1 - drift0) / 2, 126, "Model drift: error rate\nrises from 1% to 12%", fontsize=11.5, color=INK,
            ha="center", va="top", fontweight="bold")
    ax.annotate(f"Demoted to 100% at run {demote['run']:,},\n{demote['run'] - drift0} runs after drift began.\n{bad_during} bad outputs ran unaudited\nbefore the ratchet noticed.",
                xy=(demote["run"] + 30, 90), xytext=(demote["run"] + 450, 80), fontsize=11.5, color=INK, va="center",
                arrowprops=dict(arrowstyle="-", color=INK2, linewidth=1.2))
    ax.annotate("Early run: audit everything,\nthen halve as the windows come back clean", xy=(130, 50),
                xytext=(520, 80), fontsize=11.5, color=INK, va="center",
                arrowprops=dict(arrowstyle="-", color=INK2, linewidth=1.2))
    fig.text(0.047, 0.095, "Illustrative simulation using the same rules as the Logic App: promote on 2% or fewer failures over a full 50 audit window, "
             "demote above 5% once 20 audits exist.", fontsize=10.5, color=MUTED, va="center")
    fig.text(0.047, 0.065, "It assumes the auditor catches every error it samples. A real auditor will miss some, so measure it against human review too.",
             fontsize=10.5, color=MUTED, va="center")
    fig.text(0.965, 0.03, "blog.chiffers.com", fontsize=11, color=MUTED, ha="right", va="center")
    fig.savefig(OUT / "3-ratchet-in-action.png", facecolor=SURFACE)
    plt.close(fig)


if __name__ == "__main__":
    ladder()
    flow()
    ratchet()
    print("rendered:", sorted(p.name for p in OUT.iterdir()))
