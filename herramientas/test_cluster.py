"""Tests de integración: lanzan clústeres reales de ./server y validan sus logs.

    python3 herramientas/test_cluster.py
"""

import os
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from analysis import load_logs, validate  # noqa: E402
from run_cluster import SERVER_BIN, run_cluster, server_command  # noqa: E402

MSG_UPDATE, MSG_READY = 3, 5


def frame(kind, src, arg=0):
    """Trama igual que protocol.c: 3 enteros en orden de red."""
    return struct.pack("!iii", kind, src, arg)


class ClusterTest(unittest.TestCase):
    def run_ok(self, modes, port, sleep=0.0, iterations=10):
        with tempfile.TemporaryDirectory() as d:
            codes = run_cluster(modes, d, sleep, iterations, port, timeout=90)
            report = validate(load_logs(d))
        self.assertEqual(codes, [0] * len(modes))
        self.assertTrue(report["ok"], "\n".join(report["lines"]))
        return "\n".join(report["lines"])

    def test_enunciado_5_servidores(self):
        # La ejecución del enunciado: 3 rw + 2 ro, 10 iteraciones, sleep de 1 s.
        out = self.run_ok(["rw", "rw", "rw", "ro", "ro"], 16000, sleep=1.0)
        self.assertIn("valor final de la variable = 30", out)

    def test_mezcla_rw_ro(self):
        self.run_ok(["ro", "rw", "ro", "rw"], 16010, sleep=0.01)

    def test_todos_escriben_con_contencion(self):
        self.run_ok(["rw"] * 8, 16020, iterations=20)

    def test_un_solo_servidor(self):
        self.assertIn("= 10", self.run_ok(["rw"], 16030))
        self.assertIn("= 0", self.run_ok(["ro"], 16031))

    def test_solo_lectores(self):
        self.assertIn("= 0", self.run_ok(["ro", "ro", "ro"], 16040))

    def test_si_cae_un_servidor_abortan_los_demas(self):
        for victim in (1, 0):  # un servidor normal y el coordinador
            with self.subTest(victim=victim), tempfile.TemporaryDirectory() as d:
                procs = [subprocess.Popen(server_command(i, "rw", 3, d, 0.2, 10, 16050 + victim),
                                          stdout=subprocess.DEVNULL) for i in range(3)]
                time.sleep(1.0)
                procs[victim].kill()
                others = [p.wait(timeout=10) for i, p in enumerate(procs) if i != victim]
                self.assertEqual(others, [1, 1])  # nadie se queda colgado
                procs[victim].wait()

    def test_conexiones_ajenas_no_afectan(self):
        """UPDATE sin presentarse, READY con un id repetido o inválido y basura: se ignoran."""
        port = 16060

        def intruder():
            time.sleep(0.5)
            for payload in (frame(MSG_UPDATE, 1, 999), frame(MSG_READY, 1), frame(MSG_READY, 77), b"\x00" * 12):
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=2) as s:
                        s.sendall(payload)
                        time.sleep(0.1)
                except OSError:
                    pass

        t = threading.Thread(target=intruder)
        t.start()
        self.run_ok(["rw", "rw", "ro"], port, sleep=0.2)
        t.join()


class ArgumentsTest(unittest.TestCase):
    def test_argumentos_invalidos(self):
        base = ["--id", "0", "--mode", "rw", "--n", "1", "--no-wait", "--iterations", "1", "--sleep", "0"]
        for bad in (["--sleep", "nan"], ["--iterations", "basura"], ["--id", "3"], ["--mode", "xx"],
                    ["--n", "0"], ["--port", "70000"]):
            with self.subTest(args=bad), tempfile.TemporaryDirectory() as d:
                r = subprocess.run([SERVER_BIN] + base + bad + ["--log-dir", d], capture_output=True, timeout=10)
                self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
