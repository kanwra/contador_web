"""Mide cuanto se equivoca el conteo por texto (datos para la tesis).

Uso:
    python evaluar.py casos.csv
    python evaluar.py casos.csv --conf 0.15 0.25 0.35     # compara umbrales

casos.csv (con encabezado), una fila por foto:
    archivo,objetos,esperado
    fotos/manzanas1.jpg,manzanas,12
    fotos/tornillos2.jpg,tornillos,48

`esperado` es el conteo real (cuentalo tu a mano). Lo ideal: 50+ fotos
variadas (poca y mucha cantidad, buena y mala luz, objetos juntos y separados).
Guarda un CSV con el detalle por foto: resultados_<conf>.csv
"""
import argparse
import csv
import os
import statistics
import time

import contador


def evaluar(ruta_csv, conf):
    base = os.path.dirname(os.path.abspath(ruta_csv))
    filas = []
    with open(ruta_csv, newline="", encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            ruta = fila["archivo"]
            if not os.path.isabs(ruta):
                ruta = os.path.join(base, ruta)
            with open(ruta, "rb") as img:
                datos = img.read()
            esperado = int(fila["esperado"])
            t0 = time.perf_counter()
            r = contador.contar_por_texto(datos, fila["objetos"], conf)
            seg = time.perf_counter() - t0
            filas.append({"archivo": fila["archivo"], "objetos": fila["objetos"],
                          "esperado": esperado, "detectado": r["total"],
                          "error": r["total"] - esperado, "segundos": round(seg, 2)})

    errores = [abs(x["error"]) for x in filas]
    exactos = sum(1 for e in errores if e == 0)
    relativos = [abs(x["error"]) / x["esperado"] for x in filas if x["esperado"] > 0]
    resumen = {
        "conf": conf,
        "fotos": len(filas),
        "error_absoluto_medio": round(statistics.mean(errores), 2),
        "error_relativo_medio_%": round(100 * statistics.mean(relativos), 1) if relativos else None,
        "aciertos_exactos_%": round(100 * exactos / len(filas), 1),
        "sesgo": round(statistics.mean(x["error"] for x in filas), 2),  # + = cuenta de mas
        "segundos_por_foto": round(statistics.mean(x["segundos"] for x in filas), 2),
    }
    salida = "resultados_%s.csv" % conf
    with open(salida, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
        w.writeheader()
        w.writerows(filas)
    return resumen


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv")
    ap.add_argument("--conf", type=float, nargs="+", default=[0.25])
    args = ap.parse_args()
    for c in args.conf:
        print(evaluar(args.csv, c))