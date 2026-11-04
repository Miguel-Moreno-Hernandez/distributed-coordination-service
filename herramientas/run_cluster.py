"""Lanza N servidores (procesos ./server) en esta máquina y valida sus logs al terminar.

NO forma parte del sistema distribuido: es una ayuda para probar y medir sin abrir N terminales.

    python3 herramientas/run_cluster.py -n 5 --rw 3          # ejecución del enunciado (10 iter, 1 s)
    python3 herramientas/run_cluster.py -n 8 --rw 4 --sleep 0
"""

import argparse
import glob
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER_BIN = os.path.join(os.path.dirname(HERE), "server")


def server_command(server_id, mode, n, log_dir, sleep, iterations, port):
    return [SERVER_BIN, "--id", str(server_id), "--mode", mode, "--n", str(n), "--port", str(port),
            "--sleep", str(sleep), "--iterations", str(iterations), "--log-dir", log_dir, "--no-wait"]


def run_cluster(modes, log_dir, sleep=1.0, iterations=10, port=6000, timeout=None):
    """Arranca un proceso por modo (el primero es el coordinador) y devuelve sus códigos de salida."""
    if not os.path.exists(SERVER_BIN):
        raise SystemExit(f"no existe {SERVER_BIN}: compila primero con make")
    os.makedirs(log_dir, exist_ok=True)
    for old in glob.glob(os.path.join(log_dir, "node_*")):  # no mezclar con ejecuciones anteriores
        os.remove(old)
    if timeout is None:
        timeout = 60 + iterations * (sleep + 0.5) * len(modes)
    procs = []
    for i, mode in enumerate(modes):
        out = open(os.path.join(log_dir, f"node_{i}.out"), "w", encoding="utf-8")
        cmd = server_command(i, mode, len(modes), log_dir, sleep, iterations, port)
        procs.append((subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT), out))
    deadline = time.monotonic() + timeout
    codes = []
    for proc, out in procs:
        try:
            codes.append(proc.wait(timeout=max(0.1, deadline - time.monotonic())))
        except subprocess.TimeoutExpired:
            proc.kill()
            codes.append(None)
        out.close()
    return codes


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-n", type=int, default=5, help="número de servidores")
    parser.add_argument("--rw", type=int, help="cuántos son read-write (por defecto la mitad)")
    parser.add_argument("--sleep", type=float, default=1.0)
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--port", type=int, default=6000)
    parser.add_argument("--log-dir", default=os.path.join("logs", "run"))
    args = parser.parse_args()

    rw = args.n // 2 if args.rw is None else args.rw
    modes = ["rw"] * rw + ["ro"] * (args.n - rw)
    print(f"Lanzando {len(modes)} servidores: {','.join(modes)} (el servidor 0 es el coordinador)")
    start = time.monotonic()
    codes = run_cluster(modes, args.log_dir, args.sleep, args.iterations, args.port)
    print(f"Terminado en {time.monotonic() - start:.1f} s. Códigos de salida: {codes}")

    from analysis import load_logs, validate
    report = validate(load_logs(args.log_dir))
    print("\n".join(report["lines"]))
    ok = report["ok"] and all(c == 0 for c in codes)
    print("RESULTADO:", "OK" if ok else "FALLO")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
