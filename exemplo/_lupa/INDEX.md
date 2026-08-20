# Índice visual — exemplo

**6 imagens** · atualizado em 2026-08-20T14-32-00 · descrito por `gemini-2.5-flash-lite` · schema v1

> **Leia texto, nunca pixels.** Este índice existe para que você NÃO precise abrir
> as imagens. Abrir imagem custa caro e é o que este arquivo evita. Se precisar
> confirmar visualmente, abra apenas os finalistas que a busca devolveu.

## O que tem aqui

- **Por tipo:** peca: 3 · foto: 2 · logo: 1
- **Por material:** digital: 3 · na: 2 · fisico: 1

`kind`: foto · peca · captura · grafico · logo · outro
`medium`: fisico · digital · na — um mockup impresso é `peca` + `fisico`.

## Vocabulário

`azul` (2) · `tipografia` (2) · `banner` (1) · `evento` (1) · `impresso` (1) · `pao` (1) · `forno` (1) · `luz-quente` (1) · `comida` (1) · `logo` (1) · `marca` (1) · `monocromatico` (1) · `equipe` (1) · `pessoas` (1) · `madeira` (1) · `luz-natural` (1) · `ponte` (1) · `noturno` (1) · `story` (1) · `escuro` (1) · `verde` (1)

## Como consultar

1. **Achou a tag acima?** Leia `by-tag/<tag>.md`. É uma tabela pronta, com link. Pare aqui.
2. **Precisa cruzar campos** (tipo + orientação + sem texto)? Filtre `catalog.jsonl`.
   Uma linha por imagem, JSON, campos em `schema/index-v1.json`.
3. **Tem o MCP do lupa?** Chame `lupa_search` e receba os finalistas já ranqueados.

## Arquivos

| arquivo | para quê |
|---|---|
| `INDEX.md` | este mapa — leia sempre primeiro |
| `by-tag/*.md` | índice invertido, leitura barata sem código |
| `catalog.jsonl` | uma linha por imagem, para filtrar por campo |
| `contact-sheets/` | grades visuais, para curadoria humana |
| `MANIFEST.json` | estado interno: hashes que tornam a atualização incremental |
| `runs/` | o que cada rodada mudou |
