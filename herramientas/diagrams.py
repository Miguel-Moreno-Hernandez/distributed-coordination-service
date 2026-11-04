"""Genera los diagramas de la memoria. Uso: python3 herramientas/diagrams.py [carpeta_salida]"""

import math
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else "figs"

COLORS = {
    "LOCK": "#264653", "GRANT": "#2a9d8f", "UNLOCK": "#264653", "READ": "#6d597a",
    "READ_REPLY": "#6d597a", "UPDATE": "#b5523b", "UPDATE_ACK": "#b5523b",
    "READY": "#a8862a", "START": "#a8862a", "DONE": "#8a5a44",
}
BOX = "#e3f1ee"
BOX_EDGE = "#1b5e59"
NOTE = dict(fc="#faf6ee", ec="#c7b089", boxstyle="square,pad=0.4")

GAP = 2.6          # separación entre líneas de vida (pulgadas)
NOTE_WIDTH = 3.6   # anchura de la columna de notas (pulgadas)


def sequence(path, title, lifelines, messages, boxes=(), notes=(), t_scale=0.6):
    """Diagrama de secuencia.

    messages: (origen, destino, t_envío, t_llegada, etiqueta[, {'dashed', 'at'}])
    boxes:    (línea de vida, t0, t1, texto, color)
    notes:    (t, texto) en una columna a la derecha
    Los mensajes se numeran para poder citarlos desde las notas y la memoria.
    """
    xs = {name: i * GAP for i, name in enumerate(lifelines)}
    t_max = max([m[3] for m in messages] + [b[2] for b in boxes] + [n[0] for n in notes]) + 0.8
    x_notes = max(xs.values()) + 0.8
    x_max = x_notes + NOTE_WIDTH
    fig, ax = plt.subplots(figsize=(x_max + 1.2, t_scale * (t_max + 1.6)))
    ax.set_xlim(-1.2, x_max)
    ax.set_ylim(t_max, -1.4)
    ax.axis("off")
    for name, x in xs.items():
        ax.add_patch(FancyBboxPatch((x - 1.1, -1.25), 2.2, 0.8, boxstyle="round,pad=0.05", fc=BOX, ec=BOX_EDGE))
        ax.text(x, -0.85, name, ha="center", va="center", fontsize=10.5, weight="bold")
        ax.plot([x, x], [-0.4, t_max], color="black", lw=0.8, ls=(0, (4, 3)), zorder=1)
    for lifeline, t0, t1, text, color in boxes:
        x = xs[lifeline]
        ax.add_patch(plt.Rectangle((x - 0.12, t0), 0.24, t1 - t0, fc=color, ec="black", alpha=0.4, zorder=2))
        ax.text(x - 0.2, t0 + 0.15, text, ha="right", va="top", fontsize=10, style="italic")
    fig.canvas.draw()  # para conocer el ángulo real de cada flecha
    to_px = ax.transData.transform
    for number, m in enumerate(messages, start=1):
        src, dst, t0, t1, label = m[:5]
        opts = m[5] if len(m) > 5 else {}
        color = COLORS.get(label.split("(")[0].strip(), "black")
        x0, x1 = xs[src], xs[dst]
        ax.annotate("", xy=(x1, t1), xytext=(x0, t0), zorder=3,
                    arrowprops=dict(arrowstyle="-|>", color=color, lw=1.5,
                                    ls="--" if opts.get("dashed") else "-", shrinkA=0, shrinkB=0))
        f = opts.get("at", 0.5)
        lx, ly = x0 + f * (x1 - x0), t0 + f * (t1 - t0)
        (px0, py0), (px1, py1) = to_px((x0, t0)), to_px((x1, t1))
        angle = math.degrees(math.atan2(py1 - py0, px1 - px0))
        if angle > 90 or angle < -90:
            angle += 180
        ax.text(lx, ly, f"{number}: {label}", ha="center", va="bottom", fontsize=10, color=color,
                rotation=angle, rotation_mode="anchor", zorder=4, bbox=dict(fc="white", ec="none", pad=0.4, alpha=0.9))
    for t, text in notes:
        ax.text(x_notes, t, text, fontsize=10, va="center", ha="left", bbox=NOTE)
    ax.set_title(title, fontsize=13, weight="bold")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


S1, C0, S2 = "Servidor 1", "Servidor 0\n(coordinador)", "Servidor 2"


def iteration_rw():
    sequence(
        os.path.join(OUT, "seq_iteracion_rw.png"),
        "Una iteración de un servidor read-write",
        ["Servidor 1 (rw)", C0],
        [
            ("Servidor 1 (rw)", C0, 0.4, 1.2, "LOCK"),
            (C0, "Servidor 1 (rw)", 2.2, 3.0, "GRANT", {"dashed": True}),
            ("Servidor 1 (rw)", C0, 3.8, 4.6, "READ"),
            (C0, "Servidor 1 (rw)", 5.0, 5.8, "READ_REPLY(41)", {"dashed": True}),
            ("Servidor 1 (rw)", C0, 6.6, 7.4, "UPDATE(42)"),
            (C0, "Servidor 1 (rw)", 7.8, 8.6, "UPDATE_ACK", {"dashed": True}),
            ("Servidor 1 (rw)", C0, 9.4, 10.2, "UNLOCK"),
        ],
        boxes=[("Servidor 1 (rw)", 3.0, 9.4, "sección\ncrítica", "#1b7f79")],
        notes=[
            (1.6, "lock(): pide el cerrojo (1). Si está\nlibre y no hay nadie antes en la\ncola, el coordinador responde (2)."),
            (4.8, "getCurrentValue(): READ (3). El\ncoordinador responde con el valor\nde la variable, 41 (4)."),
            (7.6, "updateCurrentValue(42): UPDATE (5).\nEl coordinador guarda 42 y solo\nentonces confirma (6)."),
            (10.0, "unlock(): UNLOCK (7). Fuera de la\nSC: imprime y hace sleep(1 s)."),
        ],
    )


def conflict():
    sequence(
        os.path.join(OUT, "seq_conflicto.png"),
        "Dos peticiones a la vez: se atienden por orden de llegada",
        [S1, C0, S2],
        [
            (S1, C0, 0.4, 1.2, "LOCK"),
            (S2, C0, 0.7, 1.7, "LOCK"),
            (C0, S1, 1.6, 2.4, "GRANT", {"dashed": True}),
            (S1, C0, 2.9, 3.7, "READ"),
            (C0, S1, 4.0, 4.8, "READ_REPLY(7)", {"dashed": True}),
            (S1, C0, 5.3, 6.1, "UPDATE(8)"),
            (C0, S1, 6.4, 7.2, "UPDATE_ACK", {"dashed": True}),
            (S1, C0, 7.7, 8.5, "UNLOCK"),
            (C0, S2, 8.9, 9.7, "GRANT", {"dashed": True}),
            (S2, C0, 10.2, 11.0, "READ"),
            (C0, S2, 11.3, 12.1, "READ_REPLY(8)", {"dashed": True}),
            (S2, C0, 12.6, 13.4, "UNLOCK"),
        ],
        boxes=[(S1, 2.4, 7.7, "SC de 1", "#1b7f79"), (S2, 9.7, 12.6, "SC de 2", "#e09f3e")],
        notes=[
            (1.3, "1 y 2 piden casi a la vez (1, 2).\nEl LOCK de 1 llega antes: coge el\nturno 0; el de 2, el turno 1."),
            (4.2, "Solo 1 tiene el cerrojo. El hilo que\natiende a 2 espera su turno sin\nresponder: 2 se queda bloqueado."),
            (8.6, "Con el UNLOCK de 1 (8) avanza el\nturno y el coordinador responde\npor fin a 2 (9)."),
            (11.8, "2 lee 8: el valor que escribió 1.\nNunca lee un valor anticuado."),
        ],
        t_scale=0.62,
    )


def lifecycle():
    sequence(
        os.path.join(OUT, "seq_ciclo_vida.png"),
        "Ciclo de vida: conexión, arranque a la vez, iteraciones y fin",
        [S1, C0, S2],
        [
            (S2, C0, 1.6, 2.4, "READY"),
            (S1, C0, 2.6, 3.4, "READY"),
            (C0, S1, 4.4, 5.2, "START", {"dashed": True}),
            (C0, S2, 4.4, 5.2, "START", {"dashed": True}),
            (S2, C0, 9.0, 9.8, "DONE"),
            (S1, C0, 10.0, 10.8, "DONE"),
        ],
        boxes=[(S1, 5.4, 9.8, "10 iteraciones", "#9c9789"), (C0, 4.6, 8.6, "10 iteraciones", "#9c9789"),
               (S2, 5.4, 8.8, "10 iteraciones", "#9c9789")],
        notes=[
            (0.4, "0. El servidor 0 escucha en su puerto;\n    los demás se conectan a él (TCP)."),
            (2.4, "1. Cada uno espera ENTER y envía\n    READY (1, 2)."),
            (4.6, "2. Cuando los N están listos\n    (también el 0), START a todos (3, 4):\n    empiezan a la vez."),
            (7.0, "3. Bucle rw / ro: LOCK, READ,\n    [UPDATE], UNLOCK y sleep."),
            (10.2, "4. DONE al terminar (5, 6). El 0\n    no se cierra hasta tener el DONE\n    de todos: guarda la variable."),
        ],
    )


def lock_states():
    fig, ax = plt.subplots(figsize=(8.6, 4.2))
    for name, x in (("LIBRE", 0), ("OCUPADO\n(holder = i)", 6)):
        ax.add_patch(FancyBboxPatch((x - 1.3, -0.55), 2.6, 1.1, boxstyle="round,pad=0.1", fc=BOX, ec=BOX_EDGE))
        ax.text(x, 0, name, ha="center", va="center", weight="bold", fontsize=12)
    ax.annotate("", xy=(4.6, 0.3), xytext=(1.4, 0.3),
                arrowprops=dict(arrowstyle="-|>", lw=1.4, connectionstyle="arc3,rad=-0.3"))
    ax.text(3, 1.35, "LOCK de i: turno = next_ticket++\nle toca (now_serving == turno)\n→ GRANT", ha="center",
            fontsize=10.5)
    ax.annotate("", xy=(1.4, -0.3), xytext=(4.6, -0.3),
                arrowprops=dict(arrowstyle="-|>", lw=1.4, connectionstyle="arc3,rad=-0.3"))
    ax.text(3, -1.75, "UNLOCK de i: now_serving++\n(si la cola está vacía)", ha="center", fontsize=10.5)
    ax.annotate("", xy=(6.6, 0.62), xytext=(5.4, 0.62),
                arrowprops=dict(arrowstyle="-|>", lw=1.4, connectionstyle="arc3,rad=-1.6"))
    ax.text(6, 2.15, "UNLOCK de i con la cola no vacía:\nnow_serving++ → GRANT al siguiente turno",
            ha="center", fontsize=10.5, color="#b5523b")
    ax.text(8.0, -0.2, "LOCK mientras\nestá OCUPADO:\nespera su turno\n(cola FIFO)", fontsize=10.5, va="center",
            bbox=NOTE)
    ax.set_xlim(-1.6, 10.2)
    ax.set_ylim(-2.3, 2.9)
    ax.axis("off")
    ax.set_title("Cerrojo del coordinador (cola por turnos)", weight="bold", fontsize=13)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "cerrojo.png"), dpi=140)
    plt.close(fig)


def frame_layout():
    fields = [("tipo (int)\nREAD, LOCK...", "#cfe6e2"), ("src (int)\nid del emisor", "#9fd8ce"),
              ("arg (int)\nvalor o 0", "#f1d39c")]
    fig, ax = plt.subplots(figsize=(8.6, 2.9))
    for i, (text, color) in enumerate(fields):
        ax.add_patch(plt.Rectangle((i * 4, 0), 4, 1, fc=color, ec=BOX_EDGE))
        ax.text(i * 4 + 2, 0.5, text, ha="center", va="center", fontsize=11)
        ax.text(i * 4 + 2, 1.12, f"bytes {i * 4}-{i * 4 + 3}", ha="center", fontsize=10, color="dimgray")
    ax.text(0, -0.35, "arg según el tipo:  READ_REPLY = valor de la variable;  UPDATE = valor nuevo;  "
            "resto = 0", fontsize=10.5, va="top")
    ax.text(0, -0.85, "Los 3 enteros viajan en orden de red (htonl / ntohl).", fontsize=10.5, va="top",
            color="dimgray")
    ax.set_xlim(-0.2, 12.2)
    ax.set_ylim(-1.3, 1.45)
    ax.axis("off")
    ax.set_title("Trama de tamaño fijo: 3 enteros (12 bytes)", weight="bold", fontsize=13)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "trama.png"), dpi=140)
    plt.close(fig)


def architecture():
    fig, ax = plt.subplots(figsize=(10, 6.2))

    def box(x, y, w, h, text, fc, fs=10.5, weight="normal"):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.08", fc=fc, ec=BOX_EDGE))
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, weight=weight)

    ax.add_patch(plt.Rectangle((3.2, 0.3), 6.4, 6.6, fc="#fbfaf7", ec=BOX_EDGE, ls="--"))
    ax.text(6.4, 6.55, "Servidor 0 = coordinador", ha="center", fontsize=13, weight="bold")
    box(3.5, 4.9, 2.6, 1.0, "hilo aceptador\naccept_loop()", BOX)
    box(3.5, 2.6, 2.6, 1.6, "N-1 hilos\nserve_client()\n(uno por servidor)", BOX)
    box(6.6, 2.4, 2.7, 3.5, "estado (mutex mu\n+ cond cv)\n\nvalue (la variable)\n\ncerrojo FIFO:\nnext_ticket\nnow_serving, holder\n\n"
        "n_ready, n_done", "#f6ead2")
    box(3.5, 0.6, 5.8, 1.3, "hilo principal: run_coordinator()\nsus 10 iteraciones (sin mensajes), espera los DONE", "#d6ece8")
    for i, y in enumerate((5.0, 3.3, 1.6)):
        box(-0.2, y, 2.0, 0.9, f"Servidor {i + 1}" if i < 2 else "Servidor N-1", "#ecebe7")
        ax.annotate("", xy=(3.5, 3.4 if i else 5.4), xytext=(1.8, y + 0.45),
                    arrowprops=dict(arrowstyle="<|-|>", lw=1.3, color="#264653"))
    ax.text(0.8, 2.85, "⋮", ha="center", fontsize=16)
    ax.text(2.0, 6.15, "1 conexión TCP\npor servidor", fontsize=10, color="#264653", ha="center")
    ax.annotate("", xy=(6.6, 3.4), xytext=(6.1, 3.4), arrowprops=dict(arrowstyle="-|>", lw=1.3))
    ax.annotate("", xy=(7.9, 2.4), xytext=(7.9, 1.9), arrowprops=dict(arrowstyle="-|>", lw=1.3))
    ax.text(9.9, 3.9, "Los servidores 1..N-1 no\nhablan entre sí: cada uno\nhace sus peticiones al 0\nde una en una (envía y\nespera la respuesta).",
            fontsize=10, va="center", bbox=NOTE)
    ax.set_xlim(-0.4, 13.0)
    ax.set_ylim(0, 7.1)
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "arquitectura.png"), dpi=140)
    plt.close(fig)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    iteration_rw()
    conflict()
    lifecycle()
    lock_states()
    frame_layout()
    architecture()
    print("diagramas en", OUT)
