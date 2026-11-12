#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Gera os modelos de empacotamento (bin packing) de cada seção das provas do ENEM em formato MPS (e opcionalmente
LP), legíveis por Gurobi, SCIP, CBC, HiGHS etc. Lê as instâncias por seção gravadas por extrai_linhas.py.

Modelo:
    min  sum_j y_j
    s.a. sum_j x_ij = 1                    para toda questão i
         sum_i w_i x_ij - L_j y_j <= 0     para toda página candidata j
         x_ij, y_j binárias
A página 1 de cada seção recebe o título da seção: L_1 = L - titulo_linhas e y_1 = 1 (limite fixo); nas demais
L_j = L.
Por padrão gera o modelo completo, com m = n páginas candidatas. A opção --reduzido gera também uma variante
com m = número de páginas da heurística FFD (limite superior válido) e quebra de simetria y_j >= y_{j+1}.

Uso:
    python gera_modelo.py dados/instancias modelos             # gera <prova>_<secao>.mps (m = n)
    python gera_modelo.py dados/instancias modelos --lp        # também grava .lp
    python gera_modelo.py dados/instancias modelos --m 20      # fixa m
    python gera_modelo.py dados/instancias modelos --reduzido  # também grava ..._reduzido.mps
"""
import sys, os, json, glob, argparse


def ffd(ws, L):
    bins = []
    for w in sorted(ws, reverse=True):
        for i, b in enumerate(bins):
            if b + w <= L:
                bins[i] += w
                break
        else:
            bins.append(w)
    return len(bins)


def nome_var(s):
    """Nomes válidos para MPS e LP: sem espaços, '-', ':' etc."""
    return "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in s)


class Modelo:
    """Modelo linear inteiro genérico: colunas com coeficientes por linha, sentidos e lados direitos."""

    def __init__(self, nome):
        self.nome = nome
        self.cols = {}          # nome -> {"obj": c, "rows": [(row, coef)], "bin": True}
        self.rows = {}          # nome -> (sentido 'E'|'L'|'G', rhs)
        self.row_order = []

    def add_row(self, nome, sentido, rhs):
        self.rows[nome] = (sentido, rhs)
        self.row_order.append(nome)

    def add_col(self, nome, obj=0.0, entries=(), bin=True, fix=None):
        self.cols[nome] = {"obj": obj, "rows": list(entries), "bin": bin, "fix": fix}

    def write_mps(self, path):
        f = lambda v: ("%d" % v) if float(v).is_integer() else repr(float(v))
        with open(path, "w", encoding="ascii", newline="\n") as out:
            out.write(f"NAME          {self.nome}\n")
            out.write("ROWS\n N  obj\n")
            for r in self.row_order:
                out.write(f" {self.rows[r][0]}  {r}\n")
            out.write("COLUMNS\n")
            out.write("    MARKER                 'MARKER'                 'INTORG'\n")
            for c, d in self.cols.items():
                if d["obj"]:
                    out.write(f"    {c}  obj  {f(d['obj'])}\n")
                for r, coef in d["rows"]:
                    out.write(f"    {c}  {r}  {f(coef)}\n")
            out.write("    MARKER                 'MARKER'                 'INTEND'\n")
            out.write("RHS\n")
            for r in self.row_order:
                rhs = self.rows[r][1]
                if rhs:
                    out.write(f"    RHS  {r}  {f(rhs)}\n")
            out.write("BOUNDS\n")
            for c, d in self.cols.items():
                out.write(f" FX BOUND  {c}  {f(d['fix'])}\n" if d["fix"] is not None else f" BV BOUND  {c}\n")
            out.write("ENDATA\n")

    def write_lp(self, path):
        f = lambda v: ("%d" % v) if float(v).is_integer() else repr(float(v))
        by_row = {r: [] for r in self.row_order}
        for c, d in self.cols.items():
            for r, coef in d["rows"]:
                by_row[r].append((c, coef))
        sgn = {"E": "=", "L": "<=", "G": ">="}
        with open(path, "w", encoding="ascii", newline="\n") as out:
            out.write(f"\\ {self.nome}\nMinimize\n obj: ")
            out.write(" + ".join(f"{f(d['obj'])} {c}" for c, d in self.cols.items() if d["obj"]) + "\n")
            out.write("Subject To\n")
            for r in self.row_order:
                terms = " ".join(f"{'+' if coef >= 0 else '-'} {f(abs(coef))} {c}" for c, coef in by_row[r])
                out.write(f" {r}: {terms} {sgn[self.rows[r][0]]} {f(self.rows[r][1])}\n")
            fixos = [(c, d["fix"]) for c, d in self.cols.items() if d["fix"] is not None]
            if fixos:
                out.write("Bounds\n" + "".join(f" {c} = {f(v)}\n" for c, v in fixos))
            out.write("Binary\n")
            for c in self.cols:
                out.write(f" {c}\n")
            out.write("End\n")


def monta(inst, m, simetria):
    ids = [nome_var(i) for i in inst["ids"]]
    w, L = inst["w"], inst["L"]
    titulo = inst.get("titulo_linhas", 0)
    n = len(ids)
    mod = Modelo(f"{inst.get('nome', inst['prova'])}_m{m}" + ("_sim" if simetria else ""))
    for i in ids:
        mod.add_row(f"atrib_{i}", "E", 1)
    for j in range(1, m + 1):
        mod.add_row(f"cap_p{j}", "L", 0)
    if simetria:
        for j in range(1, m):
            mod.add_row(f"sim_p{j}", "G", 0)          # y_j - y_{j+1} >= 0
    for j in range(1, m + 1):
        for i, wi in zip(ids, w):
            mod.add_col(f"x_{i}_p{j}", 0, [(f"atrib_{i}", 1), (f"cap_p{j}", wi)])
    for j in range(1, m + 1):
        entries = [(f"cap_p{j}", -(L - titulo) if j == 1 else -L)]
        if simetria:
            if j < m:
                entries.append((f"sim_p{j}", 1))
            if j > 1:
                entries.append((f"sim_p{j-1}", -1))
        mod.add_col(f"y_p{j}", 1, entries, fix=1 if j == 1 else None)
    return mod


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dados", nargs="?", default="dados/instancias")
    ap.add_argument("saida", nargs="?", default="modelos")
    ap.add_argument("--m", type=int, default=None, help="páginas candidatas do modelo completo (padrão: n)")
    ap.add_argument("--lp", action="store_true", help="grava também arquivos .lp")
    ap.add_argument("--reduzido", action="store_true", help="gera também a variante reduzida (m = FFD, simetria)")
    a = ap.parse_args()
    os.makedirs(a.saida, exist_ok=True)
    print(f"{'instância':<22}{'n':>4}{'L':>5}{'m completo':>12}{'vars':>7}{'m reduzido':>12}{'vars':>7}")
    for path in sorted(glob.glob(os.path.join(a.dados, "instancia_*.json"))):
        inst = json.load(open(path, encoding="utf-8"))
        n = inst["n"]
        m_full = a.m or n
        mod = monta(inst, m_full, simetria=False)
        nome = inst.get("nome", inst["prova"])
        base = os.path.join(a.saida, nome)
        mod.write_mps(base + ".mps")
        if a.lp:
            mod.write_lp(base + ".lp")
        linha = f"{nome:<22}{n:>4}{inst['L']:>5}{m_full:>12}{len(mod.cols):>7}"
        if a.reduzido:
            m_red = ffd(inst["w"], inst["L"])
            red = monta(inst, m_red, simetria=True)
            red.write_mps(base + "_reduzido.mps")
            if a.lp:
                red.write_lp(base + "_reduzido.lp")
            linha += f"{m_red:>12}{len(red.cols):>7}"
        print(linha)


if __name__ == "__main__":
    main()
