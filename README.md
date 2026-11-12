# Diagramação e alocação de questões em provas: o caso do ENEM

Estudo de diagramação de provas por programação linear inteira, aplicado às provas reais do ENEM de 2021 a
2025: o modelo, os dados extraídos dos PDFs oficiais, a resolução com o SCIP e os resultados.

**Pergunta:** reordenando as questões, as provas do ENEM poderiam ter sido impressas em menos páginas?

**Resposta curta:** quase nunca. Em 8 das 10 provas a diagramação do INEP já usa o mínimo de páginas que o modelo
permite; em 2023 (1º dia) e 2024 (2º dia) seria possível economizar 1 página cada.

## 1. O problema de otimização

Cada questão `i` ocupa `w_i` linhas e não pode ser fragmentada entre páginas; cada página comporta `L` linhas.
Queremos o menor número de páginas que acomode todas as questões: um problema de empacotamento unidimensional
(*bin packing*), modelado como programa linear inteiro binário.

```
min   Σ_j y_j
s.a.  Σ_j x_ij = 1                 ∀ i          (cada questão em exatamente uma página)
      Σ_i w_i x_ij ≤ L y_j         ∀ j          (capacidade; página só recebe questões se usada)
      x_ij, y_j ∈ {0,1}
```

com `x_ij = 1` se a questão `i` vai para a página `j` e `y_j = 1` se a página `j` é usada; `m = n` páginas
candidatas, escolha segura (no pior caso, uma questão por página). Um limite inferior imediato é `⌈Σ w_i / L⌉`,
e a heurística *first-fit decreasing* (FFD) fornece um limite superior. A capacidade pode variar por página
(`L_j`): a primeira página de cada seção carrega o título da seção ("CIÊNCIAS HUMANAS... Questões de 46 a 90"),
então `L_1 = L − t`, com `t` de 2 a 4 linhas medido no PDF, e `y_1 = 1`; nas demais páginas `L_j = L`.

**Seções.** O ENEM mantém cada seção junta e começando em página nova: inglês (questões 1–5), espanhol (1–5),
Linguagens (6–45) e Ciências Humanas (46–90) no 1º dia; Ciências da Natureza (91–135) e Matemática (136–180)
no 2º. Questões de inglês e de espanhol nunca podem dividir página. Em vez de alterar a formulação, o modelo é
resolvido **uma vez por seção** e o total da prova é a soma dos ótimos. Como as páginas são bins
intercambiáveis, isso equivale a acrescentar ao modelo a proibição de páginas com seções misturadas. Esta regra
é um pouco mais estrita do que a prática do INEP, que em 2022 e 2024 colocou o fim do bloco de inglês e o
início do de espanhol na mesma página.

## 2. Dados: de PDF a `w_i` e `L`

O modelo precisa de duas coisas que não existem prontas: o tamanho `w_i` de cada questão e a capacidade `L`
da página, ambos em linhas. Os dois foram extraídos diretamente dos PDFs oficiais do INEP (cadernos de 2021 a
2025, em `provas/`) com a biblioteca PyMuPDF, pelo script `extrai_linhas.py`: para cada questão, a altura que
ela ocupa na página, do cabeçalho "QUESTÃO NN" até o fim das alternativas, incluindo figuras e tabelas, dividida
pela entrelinha do texto da prova e arredondada ao inteiro mais próximo; para a página, a altura útil das duas
colunas mais uma folga entre questões (a última questão da página não precisa dela), na mesma unidade,
arredondada para baixo. `w_i` vai de 13 a 122 linhas e `L` vale 114 ou 115 linhas em 2021–2023, 116 e 123 em
2024 e 111 em 2025.

A extração produz, em `dados/`:

- **um `.json` por seção**, que é a instância entregue ao solver (`n`, `L` e a lista de `w_i`). Uma seção é um
  conjunto de questões que a prova mantém junto e separado dos demais por quebra de página: inglês (1–5),
  espanhol (1–5), Linguagens (6–45) e Ciências Humanas (46–90) no 1º dia; Ciências da Natureza (91–135) e
  Matemática (136–180) no 2º;
- **um `.csv` por página** de cada prova, com a capacidade em linhas e o que o ENEM colocou nela;
- **um `.csv` por questão** de cada prova, com `w_i`, sua decomposição em texto, figura e espaçamento, e a
  página e coluna em que a questão foi impressa.

Detalhes do método, dos arquivos e das ressalvas estão em `dados/README.md`.

## 3. Resolução

`gera_modelo.py` escreve um arquivo MPS por seção (formato aceito por Gurobi, SCIP, CBC, HiGHS) com o modelo
exatamente como acima, `m = n`: até 2 070 variáveis binárias e 90 restrições por seção, 30 modelos no
total. `resolve_scip.py` resolve todos com o SCIP 9 (via PySCIPOpt, parâmetros padrão, limite de 600 s) e grava
`dados/resultados_scip.csv`. Todos os 30 modelos foram resolvidos até a otimalidade em 24 s no total (o mais
lento, Linguagens de 2023, em 10 s).

## 4. Resultados

Páginas de questões por prova (soma das seções):

| prova | ENEM | ótimo | economia |
|---|---|---|---|
| 2021, 1º dia | 29 | 29 | 0 |
| 2021, 2º dia | 30 | 30 | 0 |
| 2022, 1º dia | 29 | 29 | 0 |
| 2022, 2º dia | 30 | 30 | 0 |
| 2023, 1º dia | 29 | **28** | **1** |
| 2023, 2º dia | 30 | 30 | 0 |
| 2024, 1º dia | 29 | 29 | 0 * |
| 2024, 2º dia | 30 | **29** | **1** |
| 2025, 1º dia | 28 | 28 | 0 |
| 2025, 2º dia | 30 | 30 | 0 |

As economias vêm de uma seção em cada caso: Linguagens 6–45 de 2023 (13 → 12 páginas) e Matemática de 2024
(16 → 15). (*) Em 2024, 1º dia, Ciências Humanas cai de 12 para 11 páginas, mas separar o bloco de espanhol do
de inglês, que o INEP imprimiu na mesma página, custa uma página a mais: o total empata.

Observações:

- Em todas as 30 seções o ótimo coincide com o limite inferior `⌈Σ w_i / L⌉`: a relaxação linear já é justa, e
  o solver só precisa encontrar uma solução inteira com esse valor, o que explica os tempos curtos.
- O INEP, mesmo com a numeração fixa, diagrama cada seção com folga de no máximo uma página. Reordenar questões
  não traz ganho além disso porque o modelo não admite fragmentar questões e as páginas já saem quase cheias.
- Resultados por seção, com a alocação ótima de questões por página, estão em `dados/resultados_scip.csv`.

**Ressalva.** Duas simplificações do modelo fazem com que nem toda solução ótima caiba no papel. A primeira é a
estrutura de duas colunas: o modelo trata a página como um recipiente contínuo de `L` linhas, mas uma questão
só pode continuar na coluna seguinte entre duas linhas de texto, nunca no meio de uma figura, e o que sobra no
pé da coluna esquerda é uma fração de linha perdida que o modelo não vê. A segunda é o uso de inteiros: `w_i` é
arredondado ao inteiro mais próximo, então uma página com `Σ w_i = L` pode ter tamanho real um pouco maior que a
página. Isso foi contornado sem alterar o modelo: a capacidade `L` é arredondada para baixo e, quando a solução
do solver tinha uma página que não cabia no papel, foi tomada outra solução ótima do SCIP, com o mesmo número de
páginas, que não sofria desse problema. Com isso as provas remontadas fecharam sem reduzir nenhum recorte.

## 5. Provas remontadas

Para as três provas em que a solução ótima difere da impressa (`melhorias/`), `monta_pdf.py` gera
`<prova>_otimizada.pdf`. As seções sem economia, a capa, a redação e o rascunho são copiadas do PDF original;
só a seção com economia é remontada: cada questão dela é recortada do original e reposicionada na página
indicada pelo solver, mantendo numeração, cabeçalhos, rodapés e o título da seção. Dentro da página as
questões seguem a ordem original da prova; uma questão que não cabe no fim da coluna esquerda é movida inteira
para a direita quando há folga e, se não há, continua na coluna seguinte cortada entre linhas, sem cabeçalho
órfão nem alternativa viúva; a ordem só é alterada quando essas regras não fecham a página. Quando a solução do
solver tinha alguma página cujo tamanho real excedia o papel por arredondamentos e perdas fracionárias (ver a
ressalva da seção 4), foi usada outra solução ótima do SCIP, com o mesmo número de páginas, que não sofria desse
problema. Os três PDFs têm 31 páginas em vez de 32 (em 2024, 1º dia, porque os blocos de língua, copiados do
original, dividem uma página como no ENEM).

## 6. Limitações do modelo

- A capacidade por página soma as duas colunas; na prática uma figura que não cabe no fim de uma coluna deixa
  espaço vazio que o modelo não vê. Por isso o ótimo é um limite inferior do que uma diagramação real alcança;
  a busca entre soluções ótimas alternativas contorna isso quando existe uma diagramável, o que ocorreu nas três
  seções com economia.
- Textos compartilhados por várias questões (só há um, em 2025) não têm restrição de adjacência.
- `w_i` é arredondado ao inteiro mais próximo; o erro acumulado por página é de até 2 linhas em 111 a 123,
  atenuado pelo arredondamento de `L` para baixo.

## 7. Reprodução

```
pip install pymupdf pyscipopt
python extrai_linhas.py provas dados                    # PDFs -> w_i, L e instâncias por seção (dados/)
python gera_modelo.py dados/instancias modelos          # instâncias -> modelos .mps
python resolve_scip.py "modelos/*.mps" dados/resultados_scip.csv 600
python verifica_solucoes.py provas/2023_D1_CD1.pdf dados/resultados_scip.csv 60 120   # solução ótima diagramável
python monta_pdf.py provas/2023_D1_CD1.pdf dados/resultados_scip.csv melhorias/enem2023_dia1/enem2023_dia1_otimizada.pdf
```

Estrutura: `provas/` (PDFs do INEP), `dados/` (medidas por questão e por página, instâncias `.json`, resumo e
resultados), `modelos/` (MPS), `melhorias/` (provas com economia, arquivos e PDF remontado);
scripts `extrai_linhas.py`, `gera_modelo.py`, `resolve_scip.py`, `verifica_solucoes.py`, `monta_pdf.py`.
