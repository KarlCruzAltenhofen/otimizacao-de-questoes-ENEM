# Dados das provas do ENEM 2021–2025 para o problema de diagramação

Pipeline (três scripts na pasta do projeto, `pip install pymupdf pyscipopt`):

```
python extrai_linhas.py provas dados                       # PDFs -> tamanhos em linhas e instâncias por seção
python gera_modelo.py dados/instancias modelos             # instâncias -> modelos .mps (Gurobi, SCIP, ...)
python resolve_scip.py "modelos/*.mps" dados/resultados_scip.csv 600            # resolve tudo no SCIP
python verifica_solucoes.py provas/2023_D1_CD1.pdf dados/resultados_scip.csv 60 120   # solução ótima diagramável
```

Os PDFs em `provas/` vieram do INEP: `https://download.inep.gov.br/enem/provas_e_gabaritos/<ano>_PV_impresso_D1_CD1.pdf`
(1º dia, caderno 1 azul) e `..._D2_CD5.pdf` (2º dia, caderno 5 amarelo).

## Como o tamanho de cada questão foi medido

1. A prova é diagramada em duas colunas. Cada questão começa no cabeçalho "QUESTÃO NN" e termina no último
   elemento (linha de texto, imagem ou desenho vetorial) antes do cabeçalho seguinte, seguindo a ordem de leitura
   (coluna esquerda, depois direita). Algumas páginas são diagramadas em coluna única (texto ou figura de largura
   total); nelas cada elemento consome as duas colunas.
2. Mede-se a altura ocupada pela questão em pontos tipográficos (pt), somando os trechos em cada coluna que ela
   ocupa, e soma-se a folga padrão entre questões (mediana medida na prova, ~7 pt; duas vezes para questões em
   coluna única, que ocupam as duas colunas).
3. A altura é dividida pela **entrelinha do corpo do texto** medida no PDF (11,7 pt em 2021–2024/dia 1;
   11,0 pt em 2024/dia 2; 12,0 pt em 2025). O resultado é o tamanho `w` da questão em linhas. Figuras, tabelas,
   títulos, fontes e espaçamentos ficam automaticamente "traduzidos" em linhas pela altura que ocupam.
4. A capacidade de uma página é `L = ⌊(2 × altura útil da coluna + folga) / entrelinha⌋`, porque `w` inclui a
   folga após a questão e a última questão da página não precisa dela: 114 ou 115 linhas em 2021–2023, 116 (dia 1)
   e 123 (dia 2) em 2024, 111 em 2025. A página de abertura de cada seção tem um título de 2–4 linhas que reduz a
   capacidade dela (`L_1 = L − titulo_linhas` no modelo; coluna `capacidade_linhas` em `paginas_*.csv`).

A unidade "linha" só precisa ser consistente dentro de cada prova: `w` e `L` são medidos com a mesma entrelinha,
então a razão entre eles não depende do valor escolhido.

## Seções

O ENEM mantém cada seção junta e sem dividir página com outra, então o modelo é resolvido **uma vez
por seção** (mesma formulação, instâncias menores) e o total de páginas da prova é a soma dos ótimos. Como as
páginas são bins intercambiáveis, isso equivale a proibir páginas com questões de seções diferentes.

- dia 1: `ING` (01–05 inglês), `ESP` (01–05 espanhol), `LC` (06–45, inclui o texto-base de 2025), `CH` (46–90);
- dia 2: `CN` (91–135), `MT` (136–180).

Inglês e espanhol nunca podem dividir página, por isso são seções distintas. No ENEM impresso, as únicas páginas
com itens de duas seções são as dos blocos de língua em 2022 (p3: inglês + espanhol; p5: espanhol + questão 06)
e 2024 (p3: inglês + espanhol); Humanas, Natureza e Matemática começam sempre em página nova. A regra por seções
é, portanto, um pouco mais estrita do que a prática do ENEM nesses dois anos (coluna `comeca_em_pagina_nova`
em `resumo.csv`).

## Arquivos

- `questoes_<prova>.csv` — uma linha por item:
  - `id` (número da questão; `01_ING`/`01_ESP` para as questões 1–5 de inglês e espanhol; `T06-10` para o
    texto-base compartilhado de 2025), `tipo` (`questao` ou `texto_base`), `area`, `secao`, `lingua`;
  - `w` — tamanho inteiro em linhas (arredondamento ao mais próximo), `linhas` — valor fracionário;
  - decomposição: `linhas_texto` (linhas de texto fora de figuras), `linhas_texto_em_figura` (rótulos dentro de
    figuras/tabelas), `linhas_figura` (altura de imagens e desenhos em linhas), `linhas_espaco` (espaçamentos);
  - `n_imagens`, `n_desenhos`, `altura_conteudo_pt`, `altura_total_pt`;
  - posição na prova real: `pagina_inicial`, `pagina_final`, `coluna_inicial`, `n_colunas`, `coluna_unica`,
    `quebra_pagina`; `primeira_linha` é um trecho do enunciado para conferência (ilegível em parte de 2021 por
    causa da codificação das fontes do PDF; as posições estão corretas).
  Em páginas de coluna única os contadores de linhas são expressos em "linhas de coluna" (altura × 2).
- `paginas_<prova>.csv` — uma linha por página do PDF: `tipo` (capa, questoes, outra = redação/rascunho),
  `layout` (duas_colunas ou coluna_unica), `banner_linhas`, `capacidade_linhas`, `linhas_usadas` (soma dos `w`
  dos itens da página), `folga`, `itens`, `secoes`. Folgas de −1 ou −2 são efeito do arredondamento de cada `w`.
- `instancias/instancia_<prova>_<seção>.json` — instância da seção: `n`, `L`, `titulo_linhas` e `L_pagina1`
  (capacidade da página 1, que recebe o título), `ids` e `w` (na ordem da prova impressa), `w_float`, calibração
  (entrelinha, altura da coluna, linhas por coluna, folga entre questões) e as páginas reais do ENEM.
- `resumo.csv` — por seção: `n_itens`, `L`, `titulo_linhas` (linhas do título da seção na primeira página),
  `soma_w`, páginas usadas pelo ENEM, limite inferior `ceil((soma_w + titulo_linhas) / L)`, heurística first-fit
  decreasing (`ffd`) e `comeca_em_pagina_nova`.
- `resultados_scip.csv` — tabela geral de resultados, uma linha por seção de cada prova (30 linhas): `n_itens`,
  `L`, `soma_w`, `paginas_enem`, `lim_inferior`, `ffd` (vindos de `resumo.csv`), `paginas_scip` (ótimo),
  `economia` (ENEM − ótimo), `status`, `limitante`, `tempo_s`, `alocacao` (questões por página, formato
  `p1: 06 07 11; p2: ...`), que o `monta_pdf.py` usa para remontar os PDFs, e `observacao`, preenchida por
  `verifica_solucoes.py` quando a alocação foi trocada por outra solução ótima diagramável sem redução.

## Modelos (`modelos/`)

Formato MPS livre, lido por Gurobi (`gurobi_cl modelo.mps`, `gurobipy.read`), SCIP (`scip -f modelo.mps`,
`pyscipopt.Model.readProblem`), CBC, HiGHS etc. Variáveis `x_<id>_p<j>` (questão `id` na página `j`) e `y_p<j>`;
restrições `atrib_<id>` (cada questão em uma página) e `cap_p<j>` (capacidade). Um arquivo por seção,
`<prova>_<seção>.mps`, com o modelo de empacotamento tal qual: m = n páginas candidatas (até 2 070 binárias). A
página 1 recebe o título da seção: capacidade `L − titulo_linhas` e `y_p1` fixada em 1 (limite `FX` no MPS);
as demais têm capacidade `L`.
`gera_modelo.py --lp` grava também a versão `.lp`, legível; `--reduzido` gera uma variante menor (m = páginas do
FFD e quebra de simetria), não usada no trabalho.

## Resultado (SCIP 9, modelos completos: todas as seções ótimas, 24 s no total, no máximo 10 s por seção)

| prova | seção: ENEM → ótimo | total ENEM → ótimo |
|---|---|---|
| 2021 dia 1 | ING 2→2, ESP 2→2, LC 15→15, CH 10→10 | 29→29 |
| 2022 dia 1 | ING 2→2, ESP 3*→2, LC 15*→14, CH 11→11 | 29→29 |
| 2023 dia 1 | ING 2→2, ESP 2→2, LC 13→12, CH 12→12 | 29→28 |
| 2024 dia 1 | ING 2→2, ESP 2*→2, LC 14→14, CH 12→11 | 29→29 |
| 2025 dia 1 | ING 2→2, ESP 2→2, LC 14→14, CH 10→10 | 28→28 |
| 2021 dia 2 | CN 15→15, MT 15→15 | 30→30 |
| 2022 dia 2 | CN 15→15, MT 15→15 | 30→30 |
| 2023 dia 2 | CN 14→14, MT 16→16 | 30→30 |
| 2024 dia 2 | CN 14→14, MT 16→15 | 30→29 |
| 2025 dia 2 | CN 14→14, MT 16→16 | 30→30 |

(*) seção que divide página com a vizinha no ENEM; a soma por seção conta essa página duas vezes, e o total da
prova usa a contagem real de páginas. Em todos os casos o ótimo coincide com o limite inferior `ceil(soma w / L)`.

## Provas melhoradas (`melhorias/`)

Uma subpasta por prova em que a diagramação ótima difere da impressa: `enem2023_dia1` (29 → 28 páginas),
`enem2024_dia2` (30 → 29) e `enem2024_dia1` (29 → 29, mas o ENEM só chega a 29 juntando inglês e espanhol na
mesma página). Cada subpasta tem o PDF original, os CSVs, as instâncias `.json`, os `.mps`, as linhas de
`resumo.csv` e `resultados_scip.csv` da prova e o PDF remontado `<prova>_otimizada.pdf`, gerado por:

```
python monta_pdf.py provas/2023_D1_CD1.pdf dados/resultados_scip.csv melhorias/enem2023_dia1/enem2023_dia1_otimizada.pdf
```

Seções cujo ótimo tem o mesmo número de páginas do ENEM são copiadas do original, página a página, assim como
capa, redação e rascunho. Só a seção com economia é remontada: o montador recorta cada questão dela da prova
original (cabeçalho "QUESTÃO NN", texto, figuras) e a reposiciona na página indicada pela solução do solver. A
numeração original é mantida (a ordem das questões muda); cabeçalho e rodapé vêm de uma página da mesma seção,
com o número da página refeito; o título da seção vai na página 1 do solver, que no modelo tem capacidade
`L − titulo_linhas`. Dentro de uma página, questões em coluna única ficam no topo e as demais fluem em duas
colunas, na ordem original da prova. Uma questão que não cabe no fim da coluna esquerda é movida inteira para a
direita se o restante da página couber; senão é cortada entre duas linhas de texto (no meio da sobreposição das
caixas das fontes), nunca atravessando figura, com ao menos 3 linhas antes e 2 depois do corte. Só se a página
não fechar assim as questões dela são reordenadas (todas as permutações são testadas) e, em último caso, os
recortes são reduzidos uniformemente em até 1 %, o que só é permitido quando a soma real das alturas excede a
página ou fica a menos de uma linha dela (arredondamento de `w` ao inteiro e perdas nos cortes); com sobra
maior o script acusa erro em vez de reduzir. O script imprime quantas páginas precisaram de cada recurso.

Antes da remontagem, `verifica_solucoes.py` procura uma solução ótima que feche no papel sem redução: resolve a
seção com sementes aleatórias diferentes do SCIP, recolhe do pool de cada execução as soluções de valor ótimo,
descarta repetidas (a menos de renumeração de páginas) e testa cada uma página a página na diagramação acima.
A primeira que fecha substitui a alocação em `resultados_scip.csv` (coluna `observacao`). Nas três seções com
economia isso levou de 2 a 5 sementes, e nenhuma página precisou de redução.

## Observações para a modelagem

- O ENEM nunca quebra uma questão entre páginas (`quebra_pagina = 0` em todos os itens); questões podem
  continuar na coluna seguinte da mesma página. Por isso o modelo de empacotamento com capacidade `L` por página
  (duas colunas somadas) reproduz a prática real, exceto pela perda de espaço no fim de uma coluna quando uma
  figura não cabe nela.
- As páginas de redação (1º dia), a capa e a folha de rascunho não entram.
- Em 2025 (1º dia) o item `T06-10` é o texto-base das questões 06 a 10 e ocupa uma página inteira
  (`w = 110 = L`); na prova real ele deve preceder essas questões, o que o modelo básico não impõe.
- A capacidade `L` é uniforme nas instâncias; as capacidades reais por página (menores nas páginas com título de
  seção) estão em `paginas_*.csv`.
- `w` é arredondado ao inteiro mais próximo. Para um modelo mais conservador use `ceil(linhas)`; `w_float`
  está no JSON.
