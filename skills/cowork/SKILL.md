---
name: lupa-cowork
description: >-
  Use quando precisar encontrar imagens num acervo do Google Drive indexado pelo lupa
  em um ambiente SEM execução de código — Claude Cowork, claude.ai, ou qualquer agente
  que só tenha o conector do Drive. Ensina a ler o índice `_lupa/` já publicado na
  pasta do acervo e responder consultas visuais lendo dois arquivos pequenos, em vez
  de abrir dezenas de imagens. NÃO use no Claude Code com o plugin instalado (lá existe
  o MCP, que é mais rápido — use lupa-buscar). NÃO tenta indexar: sem código, o índice
  não pode ser criado nem atualizado aqui.
---

# lupa · face sem código

## O que você tem em mãos

Uma pasta de imagens no Drive que já foi indexada. Dentro dela existe `_lupa/`, um
índice **de texto**, feito para você. Você não precisa — e não deve — abrir as imagens
para descobrir o que existe no acervo.

## A regra

**Leia texto, nunca pixels.** Cada imagem que você abre custa muito mais do que o
índice inteiro. Abra imagem apenas no fim, e apenas os finalistas que a busca
apontou, e apenas se o usuário precisar de confirmação visual.

## O caminho, em três passos

**1. Leia `_lupa/INDEX.md`.** É pequeno (~2 KB) e traz o total de imagens, a divisão
por tipo e o **vocabulário de tags com contagem**. É o mapa. Leia sempre primeiro.

**2. Escolha as tags relevantes e leia `_lupa/by-tag/<tag>.md`.** Cada arquivo é uma
tabela pronta: arquivo, tipo, orientação, descrição e link. Para a maioria dos
pedidos, isto já resolve — pare aqui.

**3. Só se precisar cruzar campos, leia `_lupa/catalog.jsonl`.** Uma linha JSON por
imagem, com todos os campos. Use quando o pedido combina critérios que o `by-tag`
não separa (por exemplo: retrato **e** sem texto **e** foto).

## Os campos que evitam entregar lixo

O acervo mistura fotografia crua com peça finalizada. Filtre sempre por tipo:

- `kind`: `foto` (capturada) · `peca` (arte pronta) · `captura` (screenshot) ·
  `grafico` (diagrama) · `logo` · `outro`
- `medium`: `fisico` (impresso, objeto real) · `digital` (arte de tela) · `na`
- `has_text`: `true` quando há tipografia embutida na imagem
- `orientation`: `retrato` · `paisagem` · `quadrado`

Um mockup impresso é `peca` + `fisico`. Uma foto limpa para receber texto por cima é
`kind: foto` + `has_text: false`.

## O que responder ao usuário

Devolva poucos candidatos — cinco a dez — com **nome do arquivo, descrição curta e
link do Drive**. Diga por que cada um entrou. Se nada casar, diga qual vocabulário o
acervo realmente tem, em vez de inventar sinônimos.

## Limites desta face

- **Você não pode indexar aqui.** Se o índice estiver desatualizado ou não existir,
  avise o usuário: quem cria e atualiza é o `lupa` no Claude Code.
- **Imagens novas não aparecem** até alguém rodar `lupa update`. O `INDEX.md` mostra
  a data da última rodada — confira antes de afirmar que algo não existe.
