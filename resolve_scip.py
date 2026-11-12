#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Resolve os modelos MPS de todas as seções com o SCIP (pyscipopt) e grava um CSV geral com, por seção:
prova, seção, n_itens, L, soma_w, páginas usadas pelo ENEM, limite inferior, FFD, ótimo do SCIP, economia,
status, limitante, tempo e a alocação de questões por página.

Os dados do ENEM vêm de dados/resumo.csv (gerado por extrai_linhas.py); se não existir, grava só o resultado.

Uso:  python resolve_scip.py "modelos/*.mps" dados/resultados_scip.csv [limite_s]
"""
import sys, glob, os, time, csv
from pyscipopt import Model

ORDEM_SECOES = ["ING", "ESP", "LC", "CH", "CN", "MT"]


def resolve(path, limite):
    m = Model(); m.hideOutput(); m.readProblem(path)
    m.setParam("limits/time", limite)
    t = time.time(); m.optimize(); dt = time.time() - t
    pages = {}
    if m.getNSols() > 0:
        sol = m.getBestSol()
        for v in m.getVars():
            if v.name.startswith("x_") and m.getSolVal(sol, v) > 0.5:
                q, pg = v.name[2:].rsplit("_p", 1)
                pages.setdefault(int(pg), []).append(q)
    aloc = "; ".join(f"p{pg}: {' '.join(pages[pg])}" for pg in sorted(pages))
    nome = os.path.basename(path)[:-4]
    prova, secao = nome.rsplit("_", 1)
    return {"prova": prova, "secao": secao, "status": m.getStatus(),
            "paginas_scip": int(round(m.getObjVal())) if m.getNSols() > 0 else "",
            "limitante": round(m.getDualbound(), 3), "tempo_s": round(dt, 1), "alocacao": aloc,
            "arquivo": os.path.basename(path)}


def main():
    padrao = sys.argv[1] if len(sys.argv) > 1 else "modelos/*.mps"
    saida = sys.argv[2] if len(sys.argv) > 2 else "dados/resultados_scip.csv"
    limite = float(sys.argv[3]) if len(sys.argv) > 3 else 600
    resumo_path = os.path.join(os.path.dirname(saida) or ".", "resumo.csv")
    resumo = {}
    if os.path.exists(resumo_path):
        resumo = {(r["prova"], r["secao"]): r for r in csv.DictReader(open(resumo_path, encoding="utf-8-sig"))}
    rows = []
    for p in sorted(glob.glob(padrao)):
        r = resolve(p, limite)
        e = resumo.get((r["prova"], r["secao"]), {})
        r = {"prova": r["prova"], "secao": r["secao"],
             "n_itens": e.get("n_itens", ""), "L": e.get("L", ""), "soma_w": e.get("soma_w", ""),
             "paginas_enem": e.get("paginas_enem", ""), "lim_inferior": e.get("lim_inferior", ""), "ffd": e.get("ffd", ""),
             "paginas_scip": r["paginas_scip"],
             "economia": (int(e["paginas_enem"]) - r["paginas_scip"]) if e and r["paginas_scip"] != "" else "",
             "status": r["status"], "limitante": r["limitante"], "tempo_s": r["tempo_s"],
             "alocacao": r["alocacao"], "arquivo": r["arquivo"]}
        rows.append(r)
        print(f"{r['prova']:<14}{r['secao']:<5}{r['status']:<10} ENEM={r['paginas_enem']:>3} SCIP={r['paginas_scip']:>3} "
              f"economia={r['economia']:>2} tempo={r['tempo_s']}s", flush=True)
    rows.sort(key=lambda r: (r["prova"], ORDEM_SECOES.index(r["secao"]) if r["secao"] in ORDEM_SECOES else 99))
    with open(saida, "w", newline="", encoding="utf-8-sig") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0].keys())); wr.writeheader(); wr.writerows(rows)
    print(f"{len(rows)} seções gravadas em {saida}")


if __name__ == "__main__":
    main()
