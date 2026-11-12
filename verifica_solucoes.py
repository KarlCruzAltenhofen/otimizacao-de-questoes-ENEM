#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Procura, entre as soluções ótimas alternativas do SCIP, uma cuja diagramação feche no papel sem redução.

O modelo tem muitas soluções ótimas (grupos diferentes de questões por página com o mesmo número de páginas).
Para cada seção com economia, o script resolve o modelo várias vezes com sementes aleatórias diferentes, recolhe
do pool de cada execução todas as soluções com valor ótimo, descarta repetidas (a menos de renumeração de
páginas) e testa cada uma na diagramação de monta_pdf.py: ordem original das questões, outras ordens só para
evitar cabeçalho órfão, alternativa viúva ou figura cortada, título na página 1, nenhuma redução. A primeira
solução que fecha substitui a alocação da seção em resultados_scip.csv (coluna 'observacao' registra a origem).

Uso: python verifica_solucoes.py provas/2023_D1_CD1.pdf dados/resultados_scip.csv [sementes=30] [limite_s=120]
"""
import sys, os, csv, time, collections
from pyscipopt import Model
from extrai_linhas import Prova
from monta_pdf import Montador


def alocacao_de(sol, m):
    pages = {}
    for v in m.getVars():
        if v.name.startswith("x_") and m.getSolVal(sol, v) > 0.5:
            q, pg = v.name[2:].rsplit("_p", 1)
            pages.setdefault(int(pg), []).append(q)
    return pages


def canonica(pages):
    """Chave que ignora a numeração das páginas, exceto a página 1 (que tem o título e capacidade menor)."""
    return (frozenset(pages.get(1, [])), frozenset(frozenset(ids) for pg, ids in pages.items() if pg != 1))


def testa(mont, pages, banner):
    """Devolve (fecha?, página que falhou ou None, nº de páginas reordenadas)."""
    pg_titulo = 1 if 1 in pages else min(pages)
    reord = 0
    for pg, ids in sorted(pages.items()):
        ok, r = mont.fecha([mont.by_id[i] for i in ids], banner if pg == pg_titulo else None)
        if not ok:
            return False, tuple(sorted(ids)), reord
        reord += int(r)
    return True, None, reord


def main():
    pdf, res_csv = sys.argv[1:3]
    nsem = int(sys.argv[3]) if len(sys.argv) > 3 else 30
    limite = float(sys.argv[4]) if len(sys.argv) > 4 else 120
    pv = Prova(pdf); pv.ler(); pv.calibrar(); pv.extrair()
    mont = Montador(pv)
    rows = list(csv.DictReader(open(res_csv, encoding="utf-8-sig")))
    campos = list(rows[0].keys()) + (["observacao"] if "observacao" not in rows[0] else [])
    for r in rows:
        r.setdefault("observacao", "")
        if r["prova"] != pv.nome or int(r["paginas_scip"]) >= int(r["paginas_enem"]):
            continue
        secao, otimo = r["secao"], int(r["paginas_scip"])
        mps = os.path.join("modelos", r["arquivo"])
        banner = mont.banner_de(secao)
        t0 = time.time()
        vistas, falhas = set(), collections.Counter()
        achou = None
        # a solução já gravada é a primeira candidata
        atual = {int(p.split(": ")[0][1:]): p.split(": ")[1].split() for p in r["alocacao"].split("; ") if p}
        vistas.add(canonica(atual))
        ok, pg_falha, reord = testa(mont, atual, banner)
        if ok:
            achou = ("solução original", atual, reord)
        else:
            falhas[pg_falha] += 1
        seed = 0
        while achou is None and seed < nsem:
            m = Model(); m.hideOutput(); m.readProblem(mps)
            m.setParam("limits/time", limite)
            m.setParam("randomization/randomseedshift", seed)
            m.setParam("randomization/permutationseed", seed)
            m.setParam("randomization/permutevars", True)
            m.optimize()
            for sol in m.getSols():
                if round(m.getSolObjVal(sol)) != otimo:
                    continue
                pages = alocacao_de(sol, m)
                chave = canonica(pages)
                if chave in vistas:
                    continue
                vistas.add(chave)
                ok, pg_falha, reord = testa(mont, pages, banner)
                if ok:
                    achou = (f"semente {seed}", pages, reord)
                    break
                falhas[pg_falha] += 1
            seed += 1
        dt = time.time() - t0
        print(f"{pv.nome} {secao}: ótimo {otimo} páginas; {len(vistas)} soluções ótimas distintas testadas em {seed} sementes ({dt:.0f} s)")
        if achou:
            origem, pages, reord = achou
            print(f"   FECHA sem redução ({origem}); páginas reordenadas por órfão/viúva/figura: {reord}")
            r["alocacao"] = "; ".join(f"p{pg}: {' '.join(pages[pg])}" for pg in sorted(pages))
            r["observacao"] = f"alocação diagramável sem redução ({origem}, {len(vistas)} soluções ótimas testadas)"
        else:
            print(f"   nenhuma fecha sem redução; grupos de questões que não cabem numa página no papel (vezes):")
            for grupo, n in falhas.most_common(8):
                print(f"      {' '.join(grupo)}: {n}")
            r["observacao"] = f"nenhuma das {len(vistas)} soluções ótimas testadas fecha sem redução"
    with open(res_csv, "w", newline="", encoding="utf-8-sig") as f:
        wr = csv.DictWriter(f, fieldnames=campos); wr.writeheader(); wr.writerows(rows)


if __name__ == "__main__":
    main()
