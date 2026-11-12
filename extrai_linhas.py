#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Estima o número de linhas ocupadas por cada questão das provas do ENEM (PDFs do INEP).

Ideia geral
-----------
As provas do ENEM são diagramadas em duas colunas por página. Cada questão começa com um
cabeçalho "QUESTÃO NN" e ocupa um trecho vertical de uma ou mais colunas (uma questão pode
continuar na coluna seguinte da mesma página; algumas questões com figuras largas usam a
página em coluna única). Medimos, em pontos tipográficos (pt), a altura total ocupada pela
questão (texto, imagens raster, desenhos vetoriais e espaçamentos internos) e convertemos
em linhas dividindo pela entrelinha do corpo do texto, medida no próprio PDF. Figuras entram,
portanto, "traduzidas" em linhas pela altura que consomem. Trechos em coluna única contam
nas duas colunas (consomem a largura inteira da página).

Cada prova é dividida em seções (ING, ESP, LC, CH no dia 1; CN, MT no dia 2): conjuntos de questões que ficam
juntos e não dividem página com outra seção. O modelo é resolvido uma vez por seção.

Para cada prova é gerado:
  dados/questoes_<prova>.csv                   - uma linha por questão (tamanho em linhas, decomposição, posição no ENEM)
  dados/paginas_<prova>.csv                    - uma linha por página (capacidade em linhas, ocupação real no ENEM)
  dados/instancias/instancia_<prova>_<secao>.json - instância da seção: n, L, ids, w, páginas reais do ENEM etc.
e, ao final, dados/resumo.csv (por seção, todas as provas).

Uso:  python extrai_linhas.py provas/ dados/
"""
import sys, os, re, csv, json, math, glob, statistics, collections
import pymupdf

HEAD = re.compile(r'^\s*QUEST[ÃA]O\s+(\d{1,3})\b', re.I)
TEXTO = re.compile(r'^\s*TEXTOS?\s+PARA\s+AS\s+QUEST[ÕO]ES\s+(?:DE\s+)?(\d+)\s+(?:A|E)\s+(\d+)', re.I)


def mode_round(values, step):
    """Valor mais frequente após arredondar em múltiplos de `step`."""
    if not values:
        return None
    c = collections.Counter(round(v / step) * step for v in values)
    return c.most_common(1)[0][0]


def round_half_up(x):
    return int(math.floor(x + 0.5))


def is_white(color):
    return color is not None and all(ch >= 0.95 for ch in color[:3])


def area_of(dia, numero):
    if dia == 1:
        return "Linguagens" if numero <= 45 else "Ciências Humanas"
    return "Ciências da Natureza" if numero <= 135 else "Matemática"


# Seções: conjuntos de questões que ficam juntos e não dividem página com outra seção.
# Cada seção vira uma instância própria do modelo (a prova é a soma das seções).
SECOES = {1: ["ING", "ESP", "LC", "CH"], 2: ["CN", "MT"]}
DESCRICAO_SECAO = {"ING": "Linguagens: língua estrangeira inglês (01-05)",
                   "ESP": "Linguagens: língua estrangeira espanhol (01-05)",
                   "LC": "Linguagens, Códigos e suas Tecnologias (06-45)",
                   "CH": "Ciências Humanas e suas Tecnologias (46-90)",
                   "CN": "Ciências da Natureza e suas Tecnologias (91-135)",
                   "MT": "Matemática e suas Tecnologias (136-180)"}


def secao_de(dia, numero, lingua):
    if dia == 1:
        if numero <= 5:
            return lingua or "LC"
        return "LC" if numero <= 45 else "CH"
    return "CN" if numero <= 135 else "MT"


def ffd(ws, L):
    """Heurística first-fit decreasing: limite superior para o número de páginas."""
    bins = []
    for w in sorted(ws, reverse=True):
        for i, b in enumerate(bins):
            if b + w <= L:
                bins[i] += w
                break
        else:
            bins.append(w)
    return len(bins)


def merge_intervals(ivs, tol=0.0):
    out = []
    for a, b in sorted(ivs):
        if out and a <= out[-1][1] + tol:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


class Prova:
    def __init__(self, path):
        self.path = path
        base = os.path.basename(path)
        m = re.match(r'(\d{4})_D(\d)_CD(\d)', base)
        self.ano, self.dia, self.caderno = int(m.group(1)), int(m.group(2)), int(m.group(3))
        self.nome = f"enem{self.ano}_dia{self.dia}"
        self.doc = pymupdf.open(path)
        self.W, self.H = self.doc[0].rect.width, self.doc[0].rect.height
        self.center = self.W / 2
        self.pages = []
        self.avisos = []

    # ------------------------------------------------------------------ leitura bruta
    def ler(self):
        for pno, page in enumerate(self.doc):
            d = page.get_text("dict")
            lines, images = [], []
            for b in d["blocks"]:
                if b["type"] == 1:
                    images.append(list(b["bbox"]))
                    continue
                for l in b["lines"]:
                    txt = "".join(s["text"] for s in l["spans"])
                    if not txt.strip():
                        continue
                    s0 = max(l["spans"], key=lambda s: len(s["text"].strip()))
                    if s0["size"] < 4:
                        continue                                   # microtexto decorativo (ENEM2025ENEM2025...)
                    lines.append({
                        "x0": l["bbox"][0], "y0": l["bbox"][1], "x1": l["bbox"][2], "y1": l["bbox"][3],
                        "size": s0["size"], "font": s0["font"], "bold": "bold" in s0["font"].lower(),
                        "text": txt.strip(),
                    })
            draws, seps = [], []
            for dr in page.get_drawings():
                r = dr["rect"]
                if r.width * r.height > 0.5 * self.W * self.H:
                    continue                                   # caixas de página inteira (bleed, fundo)
                if r.width < 2 and r.height > 60 and abs(r.x0 - self.center) < 12:
                    seps.append((r.y0, r.y1))                  # candidata a linha separadora das colunas
                    continue
                if r.width < 2 and r.height > 200:
                    continue
                if is_white(dr.get("fill")) and (dr.get("color") is None or is_white(dr.get("color"))):
                    continue                                   # retângulos brancos (invisíveis)
                draws.append([r.x0, r.y0, r.x1, r.y1])
            self.pages.append({"n": pno + 1, "lines": lines, "images": images, "draws": draws, "seps": seps})

    # ------------------------------------------------------------------ calibração
    def calibrar(self):
        H = self.H
        heads = [(p["n"], l) for p in self.pages for l in p["lines"] if HEAD.match(l["text"]) and l["bold"]]
        first_left = {}
        for pn, l in heads:
            if l["x0"] < self.center:
                first_left[pn] = min(first_left.get(pn, 1e9), l["y0"])
        self.content_top = mode_round(list(first_left.values()), 0.1)
        self.content_left = mode_round([l["x0"] for _, l in heads], 1.0)

        cand = [l for p in self.pages for l in p["lines"]
                if 8.5 <= l["size"] <= 11 and not l["bold"] and self.content_top <= l["y0"] < 0.95 * H]
        self.body_size = mode_round([l["size"] for l in cand], 0.25)
        body = [l for p in self.pages for l in p["lines"]
                if abs(l["size"] - self.body_size) < 0.35 and l["y0"] >= self.content_top and l["y1"] <= 0.97 * H]
        self.content_bottom = max(l["y1"] for l in body)
        self.content_right = max(l["x1"] for l in body)
        self.col_height = self.content_bottom - self.content_top

        # entrelinha: diferenças de y0 entre linhas consecutivas (deduplicadas) do corpo do texto
        deltas = []
        for p in self.pages:
            for col in (0, 1):
                ls = sorted((l for l in body if (l["x0"] < self.center) == (col == 0) and not l["bold"]
                             and l in p["lines"]), key=lambda l: l["y0"])
                ys, last = [], -1e9
                for l in ls:
                    if l["y0"] - last < 4:
                        continue
                    ys.append(l["y0"]); last = l["y0"]
                for a, b in zip(ys, ys[1:]):
                    if 0.95 * self.body_size <= b - a <= 1.6 * self.body_size:
                        deltas.append(b - a)
        m = mode_round(deltas, 0.1)
        self.leading = round(statistics.median([d for d in deltas if abs(d - m) <= 0.25]), 3)
        self.lines_per_col = round(self.col_height / self.leading, 2)
        self.L = None            # definido em _medir, depois de medir a folga entre questões

        # a prova desenha separador de colunas? (linha vertical central de altura ~ coluna)
        head_pages = set(pn for pn, _ in heads)
        for p in self.pages:
            p["sep_full"] = any(y1 - y0 >= 0.8 * self.col_height for y0, y1 in p["seps"])
        n_sep = sum(1 for p in self.pages if p["n"] in head_pages and p["sep_full"])
        self.has_seps = n_sep >= 0.5 * len(head_pages)

    def layout_da_pagina(self, p, lines):
        """'duas_colunas' ou 'coluna_unica'. Usa o separador central quando a prova o desenha;
        senão compara linhas de texto de largura total com linhas que começam na margem da coluna direita."""
        if self.has_seps:
            return "duas_colunas" if p["sep_full"] else "coluna_unica", None
        body = [l for l in lines if abs(l["size"] - self.body_size) < 0.35 and not l["bold"]]
        ev_one = sum(1 for l in body if l["x0"] < self.center - 6 and l["x1"] > self.center + 6)
        ev_one += sum(1 for r in p["images"] + p["draws"]
                      if r[0] < self.center - 25 and r[2] > self.center + 25 and r[3] - r[1] > 10
                      and r[1] >= self.content_top and r[3] <= self.content_bottom)
        ev_two = sum(1 for l in body if self.center - 6 <= l["x0"] <= self.center + 25 and l["x1"] - l["x0"] > 100)
        if ev_one >= 2 and ev_one > ev_two:
            return "coluna_unica", (ev_one, ev_two)
        return "duas_colunas", (ev_one, ev_two)

    # ------------------------------------------------------------------ segmentação em itens
    def col_of(self, x0, x1, margin=6):
        if x1 <= self.center + margin:
            return 0
        if x0 >= self.center - margin:
            return 1
        return "full"

    def extrair(self):
        top, bot, lead = self.content_top, self.content_bottom, self.leading
        items = []
        cur = None
        self.page_info = {}
        seen_lang = 0        # 1-5 do dia 1: primeira ocorrência = inglês, segunda = espanhol
        lang = None
        for p in self.pages:
            pn = p["n"]
            lines = [l for l in p["lines"] if l["y1"] > top - 1 and l["y0"] < bot - 0.5 * lead and l["y1"] <= bot + 6]
            heads = [l for l in lines if HEAD.match(l["text"]) and l["bold"]]
            textos = [l for l in lines if TEXTO.match(l["text"])]
            if pn == 1 or (not heads and not textos):
                self.page_info[pn] = {"tipo": "capa" if pn == 1 else "outra", "banner_pt": 0.0, "banner": "", "layout": ""}
                continue

            # gráficos recortados à área útil (descarta faixas/decorações fora das margens)
            graphics = []
            for r in p["images"]:
                graphics.append(("image", r))
            for r in p["draws"]:
                graphics.append(("draw", r))
            gelems = []
            for kind, r in graphics:
                if r[2] <= self.content_left - 3 or r[0] >= self.content_right + 3:
                    continue
                y0, y1 = max(r[1], top), min(r[3], bot)
                if y1 - y0 <= 0.5:
                    continue
                gelems.append({"kind": kind, "col": self.col_of(r[0], r[2], margin=25), "y0": y0, "y1": y1,
                               "x0": r[0], "x1": r[2], "obj": r})
            lelems = [{"kind": "line", "col": self.col_of(l["x0"], l["x1"]), "y0": l["y0"], "y1": l["y1"],
                       "x0": l["x0"], "x1": l["x1"], "obj": l} for l in lines]

            # banner no topo da coluna esquerda (título da área, opção de língua)
            left_heads = [l for l in heads if l["x0"] < self.center]
            first_left_y = min((l["y0"] for l in left_heads), default=None)
            banner, keep = [], []
            if first_left_y is not None and first_left_y > top + 2:
                for e in lelems + gelems:
                    if e["y1"] > first_left_y + 1:
                        keep.append(e); continue
                    if e["kind"] == "line":
                        l = e["obj"]
                        if HEAD.match(l["text"]):
                            keep.append(e); continue
                        if e["col"] in (0, "full") or (l["bold"] and l["size"] >= self.body_size):
                            banner.append(e); continue
                        keep.append(e)
                    else:
                        if e["col"] in (0, "full"):
                            banner.append(e)
                        else:
                            keep.append(e)
            else:
                keep = lelems + gelems
            banner_txt = " | ".join(e["obj"]["text"] for e in sorted(banner, key=lambda e: e["y0"]) if e["kind"] == "line")
            banner_pt = (first_left_y - top) if banner else 0.0
            page_lang = None     # língua anunciada no banner desta página (se houver)
            if re.search(r'ingl[êe]s', banner_txt, re.I):
                page_lang = "ING"
            elif re.search(r'espanhol', banner_txt, re.I):
                page_lang = "ESP"
            # layout da página: duas colunas (ordem de leitura coluna a coluna) ou coluna única (ordem por y;
            # cada elemento consome as duas colunas)
            layout, ev = self.layout_da_pagina(p, lines)
            if ev and ev[0] >= 2 and ev[1] >= 2:
                self.avisos.append(f"p{pn}: layout ambíguo (linhas largura total={ev[0]}, linhas coluna direita={ev[1]}) -> {layout}")
            self.page_info[pn] = {"tipo": "questoes", "banner_pt": banner_pt, "banner": banner_txt, "layout": layout}
            one = layout == "coluna_unica"
            for e in keep:
                e["band"] = one
            keep.sort(key=lambda e: (0 if (one or e["col"] != 1) else 1, e["y0"], e["kind"] != "line"))

            for e in keep:
                if e["kind"] == "line":
                    l = e["obj"]
                    mh, mt = HEAD.match(l["text"]), TEXTO.match(l["text"])
                    if mh and l["bold"]:
                        num = int(mh.group(1))
                        if self.dia == 1 and num == 1:
                            # bloco de língua estrangeira: o ENEM imprime inglês primeiro, depois espanhol
                            seen_lang += 1
                            lang = page_lang or ("ING" if seen_lang == 1 else "ESP")
                        lg = lang if (self.dia == 1 and num <= 5) else None
                        if self.dia == 1 and num > 5:
                            lang = None
                        cur = {"tipo": "questao", "numero": num, "lingua": lg,
                               "id": f"{num:02d}" + (f"_{lg}" if lg else ""), "elems": [], "primeira_linha": ""}
                        items.append(cur)
                    elif mt:
                        cur = {"tipo": "texto_base", "numero": int(mt.group(1)), "lingua": None,
                               "id": f"T{int(mt.group(1)):02d}-{int(mt.group(2)):02d}", "elems": [],
                               "primeira_linha": l["text"]}
                        items.append(cur)
                if cur is None:
                    self.avisos.append(f"p{pn}: elemento antes do primeiro item ignorado: {e['kind']} "
                                       f"{e['obj']['text'][:40] if e['kind'] == 'line' else ''}")
                    continue
                e["page"] = pn
                cur["elems"].append(e)
                if e["kind"] == "line" and not cur["primeira_linha"] and not HEAD.match(e["obj"]["text"]):
                    cur["primeira_linha"] = e["obj"]["text"][:80]
        self.items = items
        self._medir()

    # ------------------------------------------------------------------ medidas
    def _segments(self, it):
        """Agrupa elementos por (página, coluna); elementos de largura total ou em coluna única contam nas duas."""
        seg = collections.defaultdict(list)
        for e in it["elems"]:
            cols = (0, 1) if (e["col"] == "full" or e["band"]) else (e["col"],)
            for c in cols:
                seg[(e["page"], c)].append(e)
        return dict(sorted(seg.items()))

    def _medir(self):
        lead = self.leading
        gaps = []
        for a, b in zip(self.items, self.items[1:]):
            if not a["elems"] or not b["elems"]:
                continue
            la = max(a["elems"], key=lambda e: e["y1"] if e["page"] == b["elems"][0]["page"] else -1)
            fb = b["elems"][0]
            if la["page"] == fb["page"] and la["col"] == fb["col"] and not la["band"] and not fb["band"]:
                g = fb["y0"] - la["y1"]
                if 0 <= g <= 2 * lead:
                    gaps.append(g)
        self.gap_pt = statistics.median(gaps) if gaps else 0.5 * lead
        # capacidade da página em linhas inteiras: duas colunas mais uma folga (w_i inclui a folga após a questão, e a
        # última questão da página não precisa dela), arredondada para baixo para nunca exceder a página física
        self.L = int((2 * self.col_height + self.gap_pt) / lead)

        for it in self.items:
            segs = self._segments(it)
            h_total = 0.0
            lines_txt = lines_in_fig = 0
            fig_h = 0.0
            n_img = sum(1 for e in it["elems"] if e["kind"] == "image")
            n_drw = sum(1 for e in it["elems"] if e["kind"] == "draw")
            w_float = 0.0
            for (pn, c), es in segs.items():
                y0 = min(e["y0"] for e in es)
                y1 = max(e["y1"] for e in es)
                h = y1 - y0
                h_total += h
                w_float += min(h / lead, self.lines_per_col)
                merged = merge_intervals([(e["y0"], e["y1"]) for e in es if e["kind"] != "line"], tol=1.0)
                fig_h += sum(b - a for a, b in merged)
                tl = sorted((e for e in es if e["kind"] == "line"), key=lambda e: e["y0"])
                last = -1e9
                for e in tl:
                    if e["y0"] - last < 4:
                        continue
                    last = e["y0"]
                    yc = (e["y0"] + e["y1"]) / 2
                    if any(a <= yc <= b for a, b in merged):
                        lines_in_fig += 1
                    else:
                        lines_txt += 1
            ncols = len(segs)
            # a folga após a questão ocupa as duas colunas quando a questão é diagramada em coluna única
            n_gaps = 2 if any(e["band"] or e["col"] == "full" for e in it["elems"]) else 1
            w_float = min(w_float + n_gaps * self.gap_pt / lead, ncols * self.lines_per_col)
            pages = sorted(set(pn for pn, _ in segs))
            first = it["elems"][0] if it["elems"] else None
            it.update({
                "secao": secao_de(self.dia, it["numero"], it["lingua"]),
                "altura_conteudo_pt": round(h_total, 1),
                "altura_total_pt": round(h_total + n_gaps * self.gap_pt, 1),
                "linhas": round(w_float, 2),
                "w": round_half_up(w_float),
                "linhas_texto": lines_txt,
                "linhas_texto_em_figura": lines_in_fig,
                "linhas_figura": round(fig_h / lead, 2),
                "n_imagens": n_img, "n_desenhos": n_drw,
                "pagina_inicial": pages[0] if pages else None,
                "pagina_final": pages[-1] if pages else None,
                "coluna_inicial": (first["col"] if first else None),
                "n_colunas": ncols,
                "coluna_unica": int(any(e["band"] or e["col"] == "full" for e in it["elems"])),
                "quebra_pagina": int(len(pages) > 1),
            })
            it["linhas_espaco"] = round(max(0.0, w_float - lines_txt - lines_in_fig - fig_h / lead), 2)

    # ------------------------------------------------------------------ saída
    def paginas(self):
        rows = []
        lead = self.leading
        for p in self.pages:
            pn = p["n"]
            info = self.page_info.get(pn, {"tipo": "outra", "banner_pt": 0.0, "banner": "", "layout": ""})
            its = [it for it in self.items if it.get("pagina_inicial") and it["pagina_inicial"] <= pn <= it["pagina_final"]]
            banner_l = round_half_up(info["banner_pt"] / lead)
            cap = self.L - banner_l if info["tipo"] == "questoes" else 0
            usado = sum(it["w"] for it in its)
            rows.append({
                "prova": self.nome, "pagina": pn, "tipo": info["tipo"], "layout": info["layout"], "banner": info["banner"],
                "banner_linhas": banner_l, "capacidade_linhas": cap,
                "linhas_usadas": usado, "linhas_usadas_float": round(sum(it["linhas"] for it in its), 2),
                "folga": cap - usado, "n_itens": len(its), "itens": " ".join(it["id"] for it in its),
                "secoes": " ".join(sorted(set(it["secao"] for it in its))),
            })
        return rows

    def write(self, outdir):
        os.makedirs(os.path.join(outdir, "instancias"), exist_ok=True)
        cols = ["prova", "ano", "dia", "caderno", "id", "tipo", "numero", "lingua", "area", "secao", "w", "linhas",
                "linhas_texto", "linhas_texto_em_figura", "linhas_figura", "linhas_espaco", "n_imagens", "n_desenhos",
                "altura_conteudo_pt", "altura_total_pt", "pagina_inicial", "pagina_final", "coluna_inicial",
                "n_colunas", "coluna_unica", "quebra_pagina", "primeira_linha"]
        qrows = []
        for it in self.items:
            r = {k: it.get(k) for k in cols}
            r.update({"prova": self.nome, "ano": self.ano, "dia": self.dia, "caderno": self.caderno,
                      "area": area_of(self.dia, it["numero"])})
            qrows.append(r)
        with open(os.path.join(outdir, f"questoes_{self.nome}.csv"), "w", newline="", encoding="utf-8-sig") as f:
            wr = csv.DictWriter(f, fieldnames=cols); wr.writeheader(); wr.writerows(qrows)
        prow = self.paginas()
        with open(os.path.join(outdir, f"paginas_{self.nome}.csv"), "w", newline="", encoding="utf-8-sig") as f:
            wr = csv.DictWriter(f, fieldnames=list(prow[0].keys())); wr.writeheader(); wr.writerows(prow)

        # uma instância por seção
        calib = {"entrelinha_pt": self.leading, "fonte_corpo_pt": self.body_size, "topo_pt": round(self.content_top, 1),
                 "base_pt": round(self.content_bottom, 1), "altura_coluna_pt": round(self.col_height, 1),
                 "linhas_por_coluna": self.lines_per_col, "folga_entre_questoes_pt": round(self.gap_pt, 2)}
        resumo, fim_anterior = [], None
        for s in SECOES[self.dia]:
            its = [it for it in self.items if it["secao"] == s]
            if not its:
                continue
            ws = [it["w"] for it in its]
            pags = sorted(set(it["pagina_inicial"] for it in its) | set(it["pagina_final"] for it in its))
            nova = fim_anterior is None or pags[0] > fim_anterior
            fim_anterior = pags[-1]
            nome = f"{self.nome}_{s}"
            # título da seção impresso no topo da primeira página (ex.: "CIÊNCIAS HUMANAS... Questões de 46 a 90"):
            # reduz a capacidade da página 1 da seção (L_1 = L - titulo_linhas no modelo)
            titulo_pt = self.page_info[pags[0]]["banner_pt"] if nova else 0.0
            titulo_linhas = math.ceil(titulo_pt / self.leading - 0.05) if titulo_pt > 0 else 0
            inst = {"nome": nome, "prova": self.nome, "ano": self.ano, "dia": self.dia, "caderno": self.caderno,
                    "arquivo": os.path.basename(self.path), "secao": s, "descricao": DESCRICAO_SECAO[s],
                    "n": len(its), "L": self.L, "titulo_linhas": titulo_linhas, "titulo_pt": round(titulo_pt, 1),
                    "L_pagina1": self.L - titulo_linhas,
                    "ids": [it["id"] for it in its], "w": ws, "w_float": [it["linhas"] for it in its],
                    "paginas_enem": {"n_paginas": len(pags), "paginas": pags, "comeca_em_pagina_nova": nova,
                                     "itens_por_pagina": {p: [it["id"] for it in its if it["pagina_inicial"] == p] for p in pags}},
                    "calibracao": calib}
            with open(os.path.join(outdir, "instancias", f"instancia_{nome}.json"), "w", encoding="utf-8") as f:
                json.dump(inst, f, ensure_ascii=False, indent=1)
            resumo.append({"prova": self.nome, "secao": s, "n_itens": len(its), "L": self.L, "titulo_linhas": titulo_linhas,
                           "soma_w": sum(ws), "w_min": min(ws), "w_max": max(ws), "paginas_enem": len(pags),
                           "lim_inferior": math.ceil((sum(ws) + titulo_linhas) / self.L), "ffd": ffd(ws, self.L),
                           "comeca_em_pagina_nova": int(nova)})
        return qrows, prow, resumo


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "provas"
    out = sys.argv[2] if len(sys.argv) > 2 else "dados"
    resumo = []
    for path in sorted(glob.glob(os.path.join(src, "*.pdf"))):
        pv = Prova(path)
        pv.ler(); pv.calibrar(); pv.extrair()
        qrows, prow, res = pv.write(out)
        resumo += res
        qpages = [r for r in prow if r["tipo"] == "questoes"]
        print(f"{pv.nome}: n={len(pv.items)} entrelinha={pv.leading} corpo={pv.body_size} topo={pv.content_top:.1f} "
              f"base={pv.content_bottom:.1f} linhas/col={pv.lines_per_col} L={pv.L} gap={pv.gap_pt:.1f} "
              f"paginas_enem={len(qpages)} col_unica={sum(it['coluna_unica'] for it in pv.items)}")
        for r in res:
            print(f"   {r['secao']:<4} n={r['n_itens']:>2} soma_w={r['soma_w']:>5} paginas_enem={r['paginas_enem']:>2} "
                  f"LB={r['lim_inferior']:>2} FFD={r['ffd']:>2}"
                  + ("" if r["comeca_em_pagina_nova"] else "  (divide página com a seção anterior)"))
        for r in prow:
            if r["tipo"] == "questoes" and r["folga"] < -2:
                print(f"   AVISO p{r['pagina']:02d} capacidade={r['capacidade_linhas']} usado={r['linhas_usadas']} itens={r['itens']}")
        for a in pv.avisos:
            print("   AVISO", a)
    with open(os.path.join(out, "resumo.csv"), "w", newline="", encoding="utf-8-sig") as f:
        wr = csv.DictWriter(f, fieldnames=list(resumo[0].keys())); wr.writeheader(); wr.writerows(resumo)


if __name__ == "__main__":
    main()
