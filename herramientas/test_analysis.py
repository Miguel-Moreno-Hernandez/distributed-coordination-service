"""Tests del validador: historiales inventados, uno correcto y otros con un defecto cada uno.

    python3 herramientas/test_analysis.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from analysis import validate  # noqa: E402


def history(sections, n=2, iterations=1, modes=("rw", "rw"), final=None):
    """sections: (servidor, t_entrada, t_salida, valor_leído, valor_escrito o None)."""
    logs = {i: [{"t": 0, "node": i, "event": "init", "mode": modes[i], "n": n, "iterations": iterations},
                {"t": 1, "node": i, "event": "start"}] for i in range(n)}
    for node, enter, leave, read, wrote in sections:
        ev = logs[node]
        ev.append({"t": enter - 1, "node": node, "event": "request_cs"})
        ev.append({"t": enter, "node": node, "event": "enter_cs"})
        ev.append({"t": enter + 1, "node": node, "event": "read", "value": read})
        if wrote is not None:
            ev.append({"t": enter + 2, "node": node, "event": "update", "value": wrote})
        ev.append({"t": leave, "node": node, "event": "exit_cs"})
    last = max([w for *_, w in sections if w is not None], default=0)
    for i in range(n):
        fin = {"t": 1000, "node": i, "event": "finished", "sent": {}}
        if i == 0:
            fin["final_value"] = last if final is None else final
        logs[i].append(fin)
    return logs


GOOD = [(0, 10, 20, 0, 1), (1, 30, 40, 1, 2)]


class ValidatorTest(unittest.TestCase):
    def test_historial_correcto(self):
        self.assertTrue(validate(history(GOOD))["ok"])

    def test_detecta_solape(self):
        self.assertFalse(validate(history([(0, 10, 35, 0, 1), (1, 30, 40, 1, 2)]))["ok"])

    def test_detecta_lectura_obsoleta(self):
        self.assertFalse(validate(history([(0, 10, 20, 0, 1), (1, 30, 40, 0, 1)]))["ok"])

    def test_detecta_incremento_mal_hecho(self):
        self.assertFalse(validate(history([(0, 10, 20, 0, 1), (1, 30, 40, 1, 5)]))["ok"])

    def test_detecta_valor_final_incorrecto(self):
        self.assertFalse(validate(history(GOOD, final=1))["ok"])

    def test_detecta_iteraciones_que_faltan(self):
        self.assertFalse(validate(history(GOOD[:1]))["ok"])

    def test_detecta_log_que_falta(self):
        logs = history(GOOD)
        del logs[1]
        self.assertFalse(validate(logs)["ok"])

    def test_detecta_fallo(self):
        logs = history(GOOD)
        logs[1].append({"t": 999, "node": 1, "event": "failure", "reason": "x"})
        self.assertFalse(validate(logs)["ok"])

    def test_detecta_escritura_de_un_ro(self):
        self.assertFalse(validate(history(GOOD, modes=("rw", "ro")))["ok"])

    def test_detecta_dos_entradas_en_la_misma_sc(self):
        logs = history(GOOD)
        logs[0].insert(4, {"t": 12, "node": 0, "event": "enter_cs"})
        self.assertFalse(validate(logs)["ok"])

    def test_detecta_escritura_antes_de_la_lectura(self):
        logs = history(GOOD)
        read, update = logs[0][4], logs[0][5]
        read["t"], update["t"] = update["t"], read["t"]
        logs[0].sort(key=lambda e: e["t"])
        self.assertFalse(validate(logs)["ok"])

    def test_detecta_operaciones_despues_de_terminar(self):
        logs = history(GOOD)
        logs[1][-1]["t"] = 25  # finished antes de su sección crítica (30-40)
        logs[1].sort(key=lambda e: e["t"])
        self.assertFalse(validate(logs)["ok"])


if __name__ == "__main__":
    unittest.main()
