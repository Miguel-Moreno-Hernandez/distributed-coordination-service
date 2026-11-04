"""Valida los logs de una ejecución, dibuja gráficas y mide cómo escala el sistema.

NO forma parte del sistema distribuido. Uso:
    python3 herramientas/analysis.py validate logs/run
    python3 herramientas/analysis.py plot logs/run --out figs/run          (necesita matplotlib)
    python3 herramientas/analysis.py benchmark --ns 2,4,8,16,32 --sleep 0 --reps 5 --out figs/bench
    python3 herramientas/analysis.py plot-benchmark figs/bench              (necesita matplotlib)

Las marcas "t" son de CLOCK_MONOTONIC: solo se pueden comparar entre procesos de la misma máquina.
"""

import glob
import json
import os
import sys


def load_logs(log_dir):
    """{id del servidor: [eventos ordenados por tiempo]}"""
    logs = {}
    for path in glob.glob(os.path.join(log_dir, "node_*.jsonl")):
        with open(path, encoding="utf-8") as fh:
            events = [json.loads(line) for line in fh if line.strip()]
        if events:
            logs[events[0]["node"]] = sorted(events, key=lambda e: e["t"])
    return dict(sorted(logs.items()))


def critical_sections(logs):
    """Reconstruye cada sección crítica (SC). Devuelve (secciones, errores de estructura)."""
    # Orden obligatorio de los eventos de un servidor:
    #   init, [connected], start, { request_cs, enter_cs, read, [update si rw], exit_cs }*, finished
    sections, errors = [], []
    for node, events in logs.items():
        mode = next(e["mode"] for e in events if e["event"] == "init")
        nxt = {"start": "request_cs", "request_cs": "enter_cs", "enter_cs": "read",
               "read": "update" if mode == "rw" else "exit_cs", "update": "exit_cs", "exit_cs": "request_cs"}
        prev, cur = None, None
        for e in events:
            kind = e["event"]
            if kind in ("init", "connected", "failure"):
                continue
            allowed = {None: ("start",), "start": ("request_cs", "finished"),
                       "exit_cs": ("request_cs", "finished")}.get(prev, (nxt.get(prev),))
            if kind not in allowed:
                errors.append(f"servidor {node}: {kind} después de {prev}")
                break
            if kind == "request_cs":
                cur = {"node": node, "mode": mode, "request": e["t"], "reads": [], "updates": []}
            elif kind == "enter_cs":
                cur["enter"] = e["t"]
            elif kind == "read":
                cur["reads"].append(e["value"])
            elif kind == "update":
                cur["updates"].append(e["value"])
            elif kind == "exit_cs":
                cur["exit"] = e["t"]
                sections.append(cur)
            prev = kind
        if prev not in ("finished", None) and not errors:
            errors.append(f"servidor {node}: el log acaba en {prev}, sin finished")
    return sorted(sections, key=lambda s: s["enter"]), errors


def validate(logs):
    """Comprueba las condiciones del enunciado. Devuelve {ok, lines, metrics}."""
    lines, ok = [], True

    def check(cond, msg):
        nonlocal ok
        ok &= bool(cond)
        lines.append(("  [OK]    " if cond else "  [FALLO] ") + msg)

    if not logs:
        return {"ok": False, "lines": ["  [FALLO] no hay logs"], "metrics": {}}
    inits = {n: next(e for e in ev if e["event"] == "init") for n, ev in logs.items()}
    n = inits[min(inits)]["n"]
    modes = {k: i["mode"] for k, i in inits.items()}
    iters = {k: i["iterations"] for k, i in inits.items()}
    expected = sum(iters[k] for k, m in modes.items() if m == "rw")
    lines.append(f"Servidores: {len(logs)} ({sum(m == 'rw' for m in modes.values())} rw)")

    check(sorted(logs) == list(range(n)), f"hay un log por cada uno de los {n} servidores")
    failures = [e["reason"] for ev in logs.values() for e in ev if e["event"] == "failure"]
    finished = {k: next((e for e in ev if e["event"] == "finished"), None) for k, ev in logs.items()}
    check(all(finished.values()) and not failures,
          "todos terminan sin fallos" + (f" (fallos: {failures})" if failures else ""))
    final = finished.get(0, {}) or {}
    check(final.get("final_value") == expected,
          f"valor final de la variable = {expected} (obtenido: {final.get('final_value')})")

    sections, errors = critical_sections(logs)
    per_node = {k: sum(s["node"] == k for s in sections) for k in logs}
    check(per_node == iters, f"cada servidor completa sus iteraciones ({per_node})")
    bad = [s for s in sections if len(s["reads"]) != 1 or len(s["updates"]) != (1 if s["mode"] == "rw" else 0)]
    check(not errors and not bad, "cada SC es: entrar, 1 lectura, [1 escritura si es rw], salir"
          + (f" ({errors[:3]})" if errors else ""))

    overlaps = sum(1 for a, b in zip(sections, sections[1:]) if b["enter"] < a["exit"])
    check(overlaps == 0, f"exclusión mutua: ninguna SC se solapa con otra ({overlaps} solapes)")
    current, stale, wrong = 0, 0, 0
    for s in sections:  # en orden de entrada
        stale += s["reads"][:1] != [current]
        if s["updates"]:
            wrong += s["reads"][:1] != [s["updates"][0] - 1]
            current = s["updates"][0]
    check(stale == 0, f"cada lectura devuelve el último valor escrito ({stale} lecturas obsoletas)")
    check(wrong == 0, f"cada escritura = lectura + 1, no se pierden incrementos ({wrong} erróneas)")

    metrics = metrics_of(logs, sections)
    lines.append(f"Espera media por la SC: {metrics['mean_wait_ms']:.2f} ms | SC media: "
                 f"{metrics['mean_cs_ms']:.3f} ms | mensajes: {metrics['messages_total']}")
    return {"ok": ok, "lines": lines, "metrics": metrics}


def metrics_of(logs, sections):
    waits = [(s["enter"] - s["request"]) / 1e6 for s in sections]
    cs = [(s["exit"] - s["enter"]) / 1e6 for s in sections]
    sent = {}
    for ev in logs.values():
        for e in ev:
            if e["event"] == "finished":
                for k, v in e.get("sent", {}).items():
                    sent[k] = sent.get(k, 0) + v
    span = (sections[-1]["exit"] - sections[0]["enter"]) / 1e9 if sections else 0
    return {"mean_wait_ms": sum(waits) / len(waits) if waits else 0.0, "max_wait_ms": max(waits, default=0.0),
            "mean_cs_ms": sum(cs) / len(cs) if cs else 0.0, "throughput": len(sections) / span if span else 0.0,
            "messages_total": sum(sent.values()), "messages_by_type": sent, "n_cs": len(sections)}


def theoretical_messages(n, n_rw, iterations=10):
    """Mensajes de una ejecución: el servidor 0 (rw) no envía nada para sí mismo."""
    rw_clients, ro_clients = n_rw - 1, n - n_rw
    return iterations * (7 * rw_clients + 5 * ro_clients) + 3 * (n - 1)


# ---------------------------------------------------------------------------- medidas
def _mean_sd(xs):
    m = sum(xs) / len(xs)
    sd = (sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5 if len(xs) > 1 else 0.0
    return m, sd


def benchmark(ns, sleep, iterations, out_dir, reps, port=7000):
    """Repite `reps` veces el clúster para cada N (mitad rw) y guarda benchmark.json."""
    from run_cluster import run_cluster
    os.makedirs(out_dir, exist_ok=True)
    results = []
    for n in ns:
        n_rw = max(1, n // 2)
        runs = []
        for r in range(reps):
            run_dir = os.path.join(out_dir, f"run_n{n}_r{r}")
            codes = run_cluster(["rw"] * n_rw + ["ro"] * (n - n_rw), run_dir, sleep, iterations, port)
            port += 1
            rep = validate(load_logs(run_dir))
            runs.append(dict(rep["metrics"], ok=rep["ok"] and all(c == 0 for c in codes)))
        res = {"n": n, "n_rw": n_rw, "reps": reps, "ok": all(x["ok"] for x in runs),
               "messages_total": runs[0]["messages_total"], "messages_by_type": runs[0]["messages_by_type"],
               "messages_identical": len({x["messages_total"] for x in runs}) == 1,
               "theoretical_total": theoretical_messages(n, n_rw, iterations),
               "max_wait_ms": max(x["max_wait_ms"] for x in runs), "runs": runs}
        for key in ("mean_wait_ms", "mean_cs_ms", "throughput"):
            res[key], res[key + "_sd"] = _mean_sd([x[key] for x in runs])
        print(f"N={n:3d}: {'OK' if res['ok'] else 'FALLO'} | espera {res['mean_wait_ms']:.2f} ± "
              f"{res['mean_wait_ms_sd']:.2f} ms (máx {res['max_wait_ms']:.1f}) | SC {res['mean_cs_ms']:.3f} ms | "
              f"{res['throughput']:.0f} SC/s | {res['messages_total']} mensajes (teórico {res['theoretical_total']})")
        results.append(res)
    with open(os.path.join(out_dir, "benchmark.json"), "w", encoding="utf-8") as fh:
        json.dump({"sleep": sleep, "iterations": iterations, "reps": reps, "results": results}, fh, indent=1)
    return results


# --------------------------------------------------------------------------- gráficas
MODE_COLORS = {"rw": "#1b7f79", "ro": "#e09f3e"}
WAIT_COLOR = "#cfcac0"
TYPE_COLORS = {"LOCK": "#264653", "GRANT": "#6b9aa6", "UNLOCK": "#9bb8bf", "READ": "#2a9d8f",
               "READ_REPLY": "#9fd8ce", "UPDATE": "#b5523b", "UPDATE_ACK": "#eab09c",
               "READY": "#d4b44a", "START": "#ead89a", "DONE": "#6d597a"}


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 11, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.titleweight": "bold", "axes.titlesize": 12})
    return plt


def _bars(ax, sections, nodes, scale, t0, min_width=0.0):
    for s in sections:
        y = nodes.index(s["node"])
        ax.barh(y, (s["enter"] - s["request"]) / scale, left=(s["request"] - t0) / scale, color=WAIT_COLOR, height=0.6)
        ax.barh(y, max((s["exit"] - s["enter"]) / scale, min_width), left=(s["enter"] - t0) / scale,
                color=MODE_COLORS[s["mode"]], height=0.6)


def plot_run(logs, out_dir):
    """timeline.png, timeline_zoom.png y waits.png de una ejecución."""
    plt = _plt()
    os.makedirs(out_dir, exist_ok=True)
    sections = critical_sections(logs)[0]
    t0 = min(e["t"] for ev in logs.values() for e in ev if e["event"] == "start")
    nodes = list(logs)
    modes = {k: next(e["mode"] for e in ev if e["event"] == "init") for k, ev in logs.items()}
    labels = [f"servidor {k} ({modes[k]})" + (" *" if k == 0 else "") for k in nodes]
    end = (sections[-1]["exit"] - t0) / 1e9

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7), sharex=True,
                                   gridspec_kw={"height_ratios": [max(2, len(nodes) * 0.4), 2]})
    _bars(ax1, sections, nodes, 1e9, t0, min_width=0.004 * end)
    ax1.set_yticks(range(len(nodes)), labels)
    ax1.invert_yaxis()
    ax1.set_title("Secciones críticas (gris = esperando el GRANT, verde = rw, ámbar = ro; * = coordinador)")
    xs, ys = [0.0], [0]
    for s in sections:
        if s["updates"]:
            xs.append((s["exit"] - t0) / 1e9)
            ys.append(s["updates"][0])
    ax2.step(xs, ys, where="post", color=MODE_COLORS["rw"])
    ax2.set_xlabel("tiempo desde el arranque (s)")
    ax2.set_ylabel("valor")
    ax2.set_title("Valor de la variable compartida")
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, "timeline.png"), dpi=130)
    plt.close(fig)

    first = sections[:len(nodes)]
    end_ms = (first[-1]["exit"] - t0) / 1e6
    fig, ax = plt.subplots(figsize=(12, max(2.5, len(nodes) * 0.55)))
    _bars(ax, [s for s in sections if (s["request"] - t0) / 1e6 <= end_ms], nodes, 1e6, t0)
    ax.set_xlim(0, end_ms * 1.05)
    ax.set_yticks(range(len(nodes)), labels)
    ax.invert_yaxis()
    ax.set_xlabel("tiempo desde el arranque (ms)")
    ax.set_title("Primera ronda ampliada (gris = esperando el GRANT, verde = rw, ámbar = ro)")
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, "timeline_zoom.png"), dpi=130)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 4))
    data = [[(s["enter"] - s["request"]) / 1e6 for s in sections if s["node"] == k] for k in nodes]
    box = ax.boxplot(data, tick_labels=[f"{k}\n{modes[k]}" for k in nodes], patch_artist=True,
                     medianprops={"color": "black"})
    for patch, k in zip(box["boxes"], nodes):
        patch.set_facecolor(MODE_COLORS[modes[k]])
        patch.set_alpha(0.75)
    ax.set_ylim(bottom=0)
    ax.set_xlabel("servidor")
    ax.set_ylabel("espera hasta entrar en la SC (ms)")
    ax.set_title("Tiempo de espera por el cerrojo")
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, "waits.png"), dpi=130)
    plt.close(fig)


def plot_benchmark(out_dir):
    """scalability.png y messages_by_type.png a partir de benchmark.json."""
    plt = _plt()
    data = json.load(open(os.path.join(out_dir, "benchmark.json"), encoding="utf-8"))
    res, sleep = data["results"], data["sleep"]
    xs = [r["n"] for r in res]
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.3))
    ax = axes[0]
    ax.plot(xs, [r["messages_total"] / (r["n"] * data["iterations"]) for r in res], "o-", color="#1b7f79")
    ax.set_title("Mensajes por operación")
    ax = axes[1]
    ax.errorbar(xs, [r["mean_wait_ms"] for r in res], yerr=[r["mean_wait_ms_sd"] for r in res], fmt="o-",
                color="#1b7f79", capsize=3, label="media ± desv.")
    ax.plot(xs, [r["max_wait_ms"] for r in res], "s--", color="#b5523b", label="máxima")
    if sleep == 0:
        ax.plot(xs, [(r["n"] - 1) * 1000 / r["throughput"] for r in res], "k:", label="modelo (N-1)·T")
    ax.set_title("Espera para entrar en la SC (ms)")
    ax.legend()
    ax = axes[2]
    if sleep == 0:
        ax.errorbar(xs, [r["throughput"] for r in res], yerr=[r["throughput_sd"] for r in res], fmt="o-",
                    color="#1b7f79", capsize=3)
        ax.set_title("Secciones críticas por segundo")
    else:
        ax.errorbar(xs, [r["mean_cs_ms"] for r in res], yerr=[r["mean_cs_ms_sd"] for r in res], fmt="o-",
                    color="#6d597a", capsize=3)
        ax.set_title("Duración media de una SC (ms)")
    for ax in axes:
        ax.set_xlabel("número de servidores N")
        ax.set_ylim(bottom=0)
        ax.grid(axis="y", ls=":", alpha=0.6)
    fig.suptitle(f"Escalabilidad (sleep = {sleep} s, {data['iterations']} iteraciones, mitad rw, "
                 f"{data['reps']} repeticiones)")
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, "scalability.png"), dpi=130)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 4.6))
    bottom = [0.0] * len(res)
    for t, color in TYPE_COLORS.items():
        vals = [100 * r["messages_by_type"].get(t, 0) / r["messages_total"] for r in res]
        ax.bar([str(x) for x in xs], vals, bottom=bottom, label=t, color=color, edgecolor="white")
        bottom = [b + v for b, v in zip(bottom, vals)]
    ax.set_xlabel("número de servidores N")
    ax.set_ylabel("% de los mensajes")
    ax.set_ylim(0, 100)
    ax.set_title("Reparto de mensajes por tipo de trama")
    ax.legend(fontsize=9, loc="center left", bbox_to_anchor=(1.01, 0.5))
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, "messages_by_type.png"), dpi=130)
    plt.close(fig)


def main(argv):
    import argparse
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate")
    v.add_argument("log_dir")
    pl = sub.add_parser("plot")
    pl.add_argument("log_dir")
    pl.add_argument("--out", default="figs")
    b = sub.add_parser("benchmark")
    b.add_argument("--ns", default="2,4,8,16,32")
    b.add_argument("--sleep", type=float, default=0.0)
    b.add_argument("--iterations", type=int, default=10)
    b.add_argument("--reps", type=int, default=5)
    b.add_argument("--port", type=int, default=7000)
    b.add_argument("--out", default=os.path.join("figs", "benchmark"))
    pb = sub.add_parser("plot-benchmark")
    pb.add_argument("out")
    a = p.parse_args(argv)
    if a.cmd == "validate":
        rep = validate(load_logs(a.log_dir))
        print("\n".join(rep["lines"]))
        print("RESULTADO:", "OK" if rep["ok"] else "FALLO")
        return 0 if rep["ok"] else 1
    if a.cmd == "plot":
        plot_run(load_logs(a.log_dir), a.out)
    elif a.cmd == "benchmark":
        res = benchmark([int(x) for x in a.ns.split(",")], a.sleep, a.iterations, a.out, a.reps, a.port)
        return 0 if all(r["ok"] for r in res) else 1
    else:
        plot_benchmark(a.out)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.exit(main(sys.argv[1:]))
