#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Monta o PDF de uma prova "melhorada": recorta cada questão da prova original (PDF do INEP) e a reposiciona
nas páginas segundo a alocação ótima do solver (dados/resultados_scip.csv), seção por seção.

- A numeração das questões, os cabeçalhos "QUESTÃO NN", figuras e filetes vêm recortados do original.
- Cabeçalho e rodapé de cada página são copiados de uma página da mesma seção; o número da página é refeito.
- Seções cujo ótimo tem o mesmo número de páginas do ENEM são copiadas do original, página a página; só as
  seções com economia são remontadas. Capa, redação e rascunho são copiadas na posição original.
- Em cada página nova, as questões diagramadas em coluna única no original ficam no topo, em largura total;
  as demais fluem em duas colunas, na ordem original da prova. Uma questão que não cabe no fim da coluna
  esquerda é movida inteira para a direita se houver folga; senão é cortada entre linhas (sem cabeçalho órfão
  nem alternativa viúva). Só se nada disso couber as questões da página são reordenadas e, em último caso,
  reduzidas em até 1 %, o que só é permitido quando a soma real das alturas excede a página ou fica a menos de
  uma linha dela (arredondamento de w para inteiro).
- A página 1 de cada seção no solver tem capacidade L - título e recebe o título da seção, que nunca é omitido.

Uso:  python monta_pdf.py provas/2023_D1_CD1.pdf dados/resultados_scip.csv melhorias/enem2023_dia1/enem2023_dia1_otimizada.pdf
"""
import sys, os, re, csv, itertools
import pymupdf
from extrai_linhas import Prova, SECOES
from gera_modelo import nome_var          # ids como aparecem nos nomes das variáveis do modelo


def ler_alocacoes(csv_path, prova):
    """{secao: [(página do solver, [ids]), ...]} a partir de resultados_scip.csv (coluna 'alocacao')."""
    out = {}
    for r in csv.DictReader(open(csv_path, encoding="utf-8-sig")):
        nome = r["arquivo"][:-4]
        if not nome.startswith(prova + "_"):
            continue
        secao = nome[len(prova) + 1:]
        out[secao] = [(int(part.split(": ")[0][1:]), part.split(": ")[1].split())
                      for part in r["alocacao"].split("; ") if part]
    return out


class Montador:
    MARGEM = 3        # folga horizontal dos recortes, em pt
    # tentativas: ordem original; outras ordens (só resolvem o espaço perdido ao evitar cabeçalho órfão, alternativa
    # viúva ou figura cortada); por fim redução de até 1 %, permitida apenas quando a soma real das alturas excede a
    # página ou fica a menos de uma linha dela (efeito do arredondamento de w para inteiro e das perdas nos cortes).
    # O título da seção nunca é omitido.
    ESCALAS = [1.0, 0.995, 0.99]

    def __init__(self, pv):
        self.pv, self.src = pv, pv.doc
        self.W, self.H = pv.W, pv.H
        self.top, self.bottom = pv.content_top, pv.content_bottom
        self.left, self.right, self.center = pv.content_left, pv.content_right, pv.center
        body = [l for p in pv.pages for l in p["lines"]
                if abs(l["size"] - pv.body_size) < 0.35 and self.top <= l["y0"] <= self.bottom]
        self.col0_right = max(l["x1"] for l in body if l["x1"] <= self.center)
        self.col1_left = min(l["x0"] for l in body if l["x0"] >= self.center)
        self.by_id = {nome_var(it["id"]): it for it in pv.items}
        self.ordem = {it["id"]: k for k, it in enumerate(pv.items)}
        self.escalas = []
        self.avisos = []

    # ------------------------------------------------------------ recortes
    def clips(self, it):
        """Recortes do item em ordem de leitura: dicts com page (0-based), rect (coords do original), full, elems."""
        out = []
        if it["coluna_unica"]:
            for pn in sorted(set(e["page"] for e in it["elems"])):
                es = [e for e in it["elems"] if e["page"] == pn]
                y0, y1 = min(e["y0"] for e in es), max(e["y1"] for e in es)
                out.append({"page": pn - 1, "rect": pymupdf.Rect(self.left - self.MARGEM, y0, self.right + self.MARGEM, y1),
                            "full": True, "elems": es})
            return out
        for (pn, c), es in self.pv._segments(it).items():
            y0, y1 = min(e["y0"] for e in es), max(e["y1"] for e in es)
            x0, x1 = ((self.left - self.MARGEM, self.col0_right + 1) if c == 0
                      else (self.col1_left - 1, self.right + self.MARGEM))
            out.append({"page": pn - 1, "rect": pymupdf.Rect(x0, y0, x1, y1), "full": False, "elems": es})
        return out

    @staticmethod
    def corte(rest, elems, y_max, y_min):
        """Maior y em [y_min, y_max] onde se pode cortar o recorte: entre duas linhas de texto (as caixas das fontes
        se sobrepõem um pouco; corta-se no meio da sobreposição) e nunca atravessando imagem, desenho ou o miolo de
        uma linha. None se não houver."""
        def miolo(e):
            h = e["y1"] - e["y0"]
            return (e["y0"] + 0.25 * h, e["y1"] - 0.25 * h) if e["kind"] == "line" else (e["y0"], e["y1"])
        linhas = sorted({(round(e["y0"], 1), round(e["y1"], 1)) for e in elems if e["kind"] == "line"})
        cand = {e["y1"] for e in elems}
        for (a0, a1), (b0, b1) in zip(linhas, linhas[1:]):
            cand.add((a1 + b0) / 2 if b0 < a1 else a1)
        miolos = [miolo(e) for e in elems]
        for y in sorted(cand, reverse=True):
            if not (rest.y0 < y < rest.y1) or y > y_max or y < y_min:
                continue
            if not any(c0 < y - 0.3 and c1 > y + 0.3 for c0, c1 in miolos):
                return y
        return None

    # ------------------------------------------------------------ diagramação de uma página
    def fluir(self, itens_full, itens_narrow, banner, s):
        """Diagrama a página na ordem dada. Devolve (ok, placements, band_top, estatísticas).

        Regra: cada questão entra na coluna esquerda enquanto couber. Quando não cabe, se o que falta diagramar
        couber inteiro na coluna direita, a questão é movida inteira (sem corte); senão ela é cortada entre linhas,
        nunca atravessando figura, com ao menos 3 linhas antes e 2 depois do corte."""
        top, bottom, left = self.top, self.bottom, self.left - self.MARGEM
        gap = self.pv.gap_pt * s
        pl = []
        st = {"cortes": 0, "movidos": 0, "sobra_col0_pt": 0.0}
        y = top
        for it, cl in itens_full:
            for c in cl:
                h, w = c["rect"].height * s, c["rect"].width * s
                if y + h > bottom + 0.01:
                    return False, None, None, None
                pl.append((c["page"], c["rect"], pymupdf.Rect(left, y, left + w, y + h)))
                y += h
            y += gap
        band_top = y
        xs = [left, self.col1_left - 1]
        ys = [band_top, band_top]
        if banner is not None:
            h, w = banner["rect"].height * s, banner["rect"].width * s
            pl.append((banner["page"], banner["rect"], pymupdf.Rect(xs[0], ys[0], xs[0] + w, ys[0] + h)))
            ys[0] += h + 3 * s
        # sequência de recortes e altura que ainda falta diagramar a partir de cada um (com as folgas)
        seq = [(c, j == len(cl) - 1) for it, cl in itens_narrow for j, c in enumerate(cl)]
        falta = [0.0] * (len(seq) + 1)
        for idx in range(len(seq) - 1, -1, -1):
            c, ultimo = seq[idx]
            falta[idx] = falta[idx + 1] + c["rect"].height * s + (gap if ultimo else 0)
        ci = 0
        for idx, (c, ultimo) in enumerate(seq):
            rest = pymupdf.Rect(c["rect"])
            while True:
                space = bottom - ys[ci]
                h, w = rest.height * s, rest.width * s
                if h <= space + 0.01:
                    pl.append((c["page"], pymupdf.Rect(rest), pymupdf.Rect(xs[ci], ys[ci], xs[ci] + w, ys[ci] + h)))
                    ys[ci] += h
                    break
                if ci == 1:
                    return False, None, None, None
                y_cut = None
                if falta[idx] > (bottom - ys[1]) + 0.01:          # mover inteira não cabe: tenta cortar
                    lead = self.pv.leading
                    y_cut = self.corte(rest, c["elems"], min(rest.y0 + space / s, rest.y1 - 2 * lead), rest.y0 + 3 * lead)
                if y_cut is not None:
                    parte = pymupdf.Rect(rest.x0, rest.y0, rest.x1, y_cut)
                    pl.append((c["page"], parte, pymupdf.Rect(xs[0], ys[0], xs[0] + w, ys[0] + parte.height * s)))
                    ys[0] += parte.height * s
                    rest = pymupdf.Rect(rest.x0, y_cut, rest.x1, rest.y1)
                    st["cortes"] += 1
                else:
                    st["movidos"] += 1
                st["sobra_col0_pt"] = max(0.0, bottom - ys[0])
                ci = 1
            if ultimo:
                ys[ci] += gap
        return True, pl, band_top, st

    def preparar(self, itens):
        """Separa itens de largura total (ficam no topo da página) e de coluna, na ordem original da prova."""
        itens = sorted(itens, key=lambda it: self.ordem[it["id"]])
        cls = [(it, self.clips(it)) for it in itens]
        itens_full = [(it, cl) for it, cl in cls if cl and cl[0]["full"]]
        itens_narrow = [(it, cl) for it, cl in cls if cl and not cl[0]["full"]]
        gap = self.pv.gap_pt
        need = (2 * sum(sum(c["rect"].height for c in cl) + gap for _, cl in itens_full)
                + sum(sum(c["rect"].height for c in cl) + gap for _, cl in itens_narrow))
        return itens_full, itens_narrow, need

    def montar_pagina(self, out, itens, banner, template, numero):
        itens_full, itens_narrow, need = self.preparar(itens)
        ordens = [tuple(itens_narrow)]
        if 1 < len(itens_narrow) <= 7:
            ordens += [o for o in itertools.permutations(itens_narrow) if o != ordens[0]]
        H2, gap = 2 * self.pv.col_height, self.pv.gap_pt
        # excesso da soma real das alturas sobre a página (a folga após a última questão da página não conta)
        excesso = need + (banner["rect"].height + 3 if banner else 0) - gap - H2
        best = None
        for s in self.ESCALAS:
            if s < 1.0 and excesso <= -self.pv.leading:      # sobra de uma linha ou mais: o problema não é arredondamento
                raise RuntimeError(f"página {numero}: não fecha por diagramação apesar de {-excesso:.0f} pt de sobra "
                                   f"({[it['id'] for it in itens]})")
            for i, ordem in enumerate(ordens):
                ok, pl, band_top, st = self.fluir(itens_full, list(ordem), banner, s)
                if ok:
                    best = (pl, band_top, st, s, i > 0)
                    break
            if best:
                break
        if best is None:
            raise RuntimeError(f"página {numero}: itens não cabem ({[it['id'] for it in itens]}); excesso real {excesso:.0f} pt")
        pl, band_top, st, s, reordenada = best
        st.update({"escala": s, "reordenada": reordenada, "excesso_pt": round(excesso, 1)})
        self.escalas.append((numero, round(s, 3), [it["id"] for it in itens], st))
        page = self.nova_pagina(out, template, numero)
        for pno, src_rect, dst_rect in pl:
            page.show_pdf_page(dst_rect, self.src, pno, clip=src_rect)
        if itens_narrow:
            page.draw_line((self.center, band_top + 3), (self.center, self.bottom), color=(0.15, 0.15, 0.15), width=0.5)
        return page

    def fecha(self, itens, banner):
        """Testa, sem redução, se a página fecha: ordem original e, se preciso, outras ordens. Devolve (ok, reordenada)."""
        itens_full, itens_narrow, _ = self.preparar(itens)
        ordens = [tuple(itens_narrow)]
        if 1 < len(itens_narrow) <= 7:
            ordens += [o for o in itertools.permutations(itens_narrow) if o != ordens[0]]
        for i, ordem in enumerate(ordens):
            ok, *_ = self.fluir(itens_full, list(ordem), banner, 1.0)
            if ok:
                return True, i > 0
        return False, False

    def banner_de(self, secao):
        """Recorte do título da seção na primeira página original dela (None se a seção não tem título próprio)."""
        itens_secao = [it for it in self.pv.items if it["secao"] == secao]
        primeira = min(it["pagina_inicial"] for it in itens_secao)
        banner_pt = self.pv.page_info[primeira]["banner_pt"]
        if banner_pt <= 0:
            return None
        return {"page": primeira - 1, "rect": pymupdf.Rect(self.left - self.MARGEM, self.top, self.col0_right + 1,
                                                            self.top + banner_pt - 1)}

    # ------------------------------------------------------------ página nova com cabeçalho e rodapé do original
    def nova_pagina(self, out, template, numero):
        page = out.new_page(width=self.W, height=self.H)
        W, H = self.W, self.H
        faixas = [pymupdf.Rect(0, 0, W, self.top - 3), pymupdf.Rect(0, self.bottom + 4, W, H),
                  pymupdf.Rect(0, 0, self.left - 6, H), pymupdf.Rect(self.right + 6, 0, W, H)]
        for r in faixas:
            page.show_pdf_page(r, self.src, template, clip=r)
        self._renumerar(page, template, numero)
        return page

    def _renumerar(self, page, template, numero):
        """Cobre o número de página impresso (vindo do original) e escreve o novo no mesmo lugar."""
        for l in self.pv.pages[template]["lines"]:
            if l["y0"] > self.bottom and re.fullmatch(r"\d{1,2}", l["text"]):
                r = pymupdf.Rect(l["x0"] - 2, l["y0"], l["x1"] + 8, l["y1"])
                page.draw_rect(r, color=None, fill=(1, 1, 1))
                page.insert_text((l["x0"], l["y1"] - 0.22 * l["size"]), str(numero), fontsize=l["size"], fontname="helv")
                return

    # ------------------------------------------------------------ prova inteira
    def montar(self, alocacoes, saida):
        """Monta a prova: seções cujo ótimo tem o mesmo número de páginas do ENEM são copiadas do original, página a
        página; as demais são remontadas com a alocação do solver. Capa, redação e rascunho são copiadas."""
        pv = self.pv
        out = pymupdf.open()
        secao_da_pagina = {}
        for it in pv.items:
            secao_da_pagina.setdefault(it["pagina_inicial"], it["secao"])
        extras = {None: []}
        atual = None
        for p in pv.pages:
            pn = p["n"]
            if pn in secao_da_pagina:
                atual = secao_da_pagina[pn]
            elif pv.page_info.get(pn, {}).get("tipo") in ("capa", "outra"):
                extras.setdefault(atual, []).append(pn)
        numero = 0
        resumo = []
        copiadas = set()

        def copiar(pn):
            nonlocal numero
            if pn in copiadas:
                return
            copiadas.add(pn)
            numero += 1
            out.insert_pdf(self.src, from_page=pn - 1, to_page=pn - 1)
            self._renumerar(out[-1], pn - 1, numero)

        for pn in extras[None]:
            copiar(pn)
        for secao in SECOES[pv.dia]:
            paginas = alocacoes.get(secao)
            if not paginas:
                continue
            itens_secao = [it for it in pv.items if it["secao"] == secao]
            orig_pages = sorted(set(it["pagina_inicial"] for it in itens_secao))
            if len(paginas) >= len(orig_pages):
                for pn in orig_pages:
                    copiar(pn)
                resumo.append((secao, len(orig_pages), len(orig_pages), "copiada do original"))
            else:
                templates = {par: next((p for p in orig_pages if p % 2 == par), orig_pages[0]) for par in (0, 1)}
                banner = self.banner_de(secao)
                # a página 1 do solver tem capacidade L - título e recebe o título da seção; as demais seguem a
                # ordem original das questões
                p1 = [[self.by_id[i] for i in ids] for pg, ids in paginas if pg == 1]
                outras = [[self.by_id[i] for i in ids] for pg, ids in paginas if pg != 1]
                outras.sort(key=lambda its: min(self.ordem[it["id"]] for it in its))
                paginas = p1 + outras
                for k, its in enumerate(paginas):
                    numero += 1
                    self.montar_pagina(out, its, banner if k == 0 else None, templates[numero % 2] - 1, numero)
                resumo.append((secao, len(orig_pages), len(paginas), "remontada"))
            for pn in extras.get(secao, []):
                copiar(pn)
        out.save(saida, garbage=3, deflate=True)
        return resumo, numero


def main():
    pdf, res_csv, saida = sys.argv[1:4]
    pv = Prova(pdf)
    pv.ler(); pv.calibrar(); pv.extrair()
    aloc = ler_alocacoes(res_csv, pv.nome)
    m = Montador(pv)
    resumo, n = m.montar(aloc, saida)
    print(f"{saida}: {n} páginas (original {len(pv.doc)})")
    for secao, orig, novo, como in resumo:
        print(f"   {secao:<4} {orig:>2} -> {novo:>2} páginas ({como})")
    lead = pv.leading
    est = [e[3] for e in m.escalas]
    if est:
        print(f"   páginas remontadas: {len(est)}; na ordem original: {sum(1 for e in est if not e['reordenada'])}; "
              f"reordenadas: {sum(1 for e in est if e['reordenada'])}; "
              f"reduzidas: {sum(1 for e in est if e['escala'] < 1)} "
              + ", ".join(f"(p{n} {s_}, soma real {'excede a página em' if st['excesso_pt'] > 0 else 'fica a'} "
                          f"{abs(st['excesso_pt'])} pt{'' if st['excesso_pt'] > 0 else ' da página'})"
                          for n, s_, _, st in m.escalas if s_ < 1))
        print(f"   cortes entre colunas: {sum(e['cortes'] for e in est)}; questões movidas inteiras de coluna: "
              f"{sum(e['movidos'] for e in est)}; linhas perdidas no pé da coluna esquerda: "
              f"{sum(e['sobra_col0_pt'] for e in est) / lead:.1f}")
    for a in m.avisos:
        print("   AVISO", a)


if __name__ == "__main__":
    main()
