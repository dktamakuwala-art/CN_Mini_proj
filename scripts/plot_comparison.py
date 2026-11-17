#!/usr/bin/env python3
"""Plot results/sdn_vs_static.csv -> results/sdn_vs_static.png"""
import csv, os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
rows = list(csv.DictReader(open(os.path.join(ROOT, "results", "sdn_vs_static.csv"))))
fig, ax = plt.subplots(1, 3, figsize=(15, 4))
for mode, style in (("static", "o--"), ("sdn", "s-")):
    r = [x for x in rows if x["mode"] == mode]
    x = [float(i["total_background_mbps"]) for i in r]
    f = lambda k: [float(i[k]) if i.get(k) not in (None, "") else float("nan") for i in r]
    ax[0].plot(x, f("avg_latency_s"), style, label=mode)
    ax[1].plot(x, f("delivery_percent"), style, label=mode)
    ax[2].plot(x, f("retransmissions"), style, label=mode)
for a, t, y in zip(ax, ("Emergency latency vs congestion", "Delivery success", "Retransmissions"),
                   ("avg latency (s)", "%", "count")):
    a.set_title(t); a.set_xlabel("Background load (Mbps, into 10 Mbps port)"); a.set_ylabel(y)
    a.grid(alpha=.3); a.legend()
plt.tight_layout()
plt.savefig(os.path.join(ROOT, "results", "sdn_vs_static.png"), dpi=150)
print("saved")
