---
name: lupa-indexar
description: >-
  Use quando o usuário quiser CRIAR ou ATUALIZAR o índice de um acervo de imagens do
  Google Drive — "indexa essas fotos", "atualiza o índice do acervo", "cataloga essa
  pasta de imagens", "o que mudou nas referências". Descreve cada imagem uma única vez
  com um modelo de visão barato e escreve um índice textual (`_lupa/`) dentro da própria
  pasta do Drive, para que qualquer agente encontre imagens SEM abri-las. Incremental:
  a segunda rodada só paga pelo que mudou. NÃO use para buscar no índice já existente
  (isso é a skill lupa-buscar) nem para julgar se uma imagem serve a uma marca.
---

# lupa · indexar

## O que esta skill faz

Transforma uma pasta de imagens do Drive num índice de texto. Cada imagem ganha
descrição, tags, tipo, paleta e orientação. O índice vive em `_lupa/`, dentro da
própria pasta do acervo — assim tanto o Claude Code quanto o Cowork o alcançam.

**Ela não tem opinião.** Não sabe o que é cliente, marca ou linha editorial. Quem
julga adequação é a skill consumidora.

## Antes de rodar

1. **O acervo está cadastrado?** `~/.francis/config/lupa.json` precisa ter o par
   `nome` → `folder_id` (o id da pasta na URL do Drive).
2. **As credenciais existem?** `~/.francis/secrets/lupa/lupa.env` com `GEMINI_API_KEY`
   preenchida, e `google-oauth.json` baixado. O README de lá tem o passo a passo.

## Os dois verbos

```bash
python3 -m lupa index <acervo>     # primeira vez na vida do acervo
python3 -m lupa update <acervo>    # todas as outras vezes
```

**Sempre prefira `update`.** Ele reconcilia: descreve as novas, redescreve as que
mudaram de conteúdo, remove do catálogo as que sumiram, e **pula as intactas sem
gastar nada**. Rodar `update` num acervo sem mudanças custa zero.

O `index` só serve para o primeiro dia. Se o acervo já tem índice, ele se recusa a
agir e manda você para o `update` — porque refazer custa dinheiro e apaga histórico.

## Antes de gastar, planeje

```bash
python3 -m lupa update <acervo> --dry-run
```

Mostra quantas imagens seriam descritas e o custo estimado, sem escrever nada e
sem chamar o modelo. **Use isto sempre que o acervo for grande ou desconhecido.**

Acima de 200 imagens novas, o comando pergunta antes de prosseguir. Para rodar sem
interação (agente autônomo), passe `--yes` — mas só depois de ter visto o `--dry-run`.

## Refazer do zero (raro, e caro)

```bash
python3 -m lupa index <acervo> --rebuild --confirm "<nome-do-acervo>"
```

Exige digitar o nome do acervo. O índice anterior é copiado para `_lupa/.backup/`
antes de qualquer escrita. Só faça isso se o schema mudou ou se o índice corrompeu.

## Ao terminar

O comando imprime o resumo da rodada e publica o `_lupa/` no Drive. Relate ao
usuário o que mudou (`+N novas · ~N alteradas · -N removidas`) e o custo. Se houver
falhas, elas estão em `_lupa/runs/<data>.errors.jsonl` — mencione quantas foram.

## Erros comuns

| Sintoma | Causa | Saída |
|---|---|---|
| `✋ Este acervo já tem índice` | usou `index` no lugar de `update` | rode `update` |
| `⏳ Outra execução está usando este índice` | duas rodadas ao mesmo tempo | espere, ou apague `_lupa/.lock` se tiver certeza |
| `GEMINI_API_KEY vazia` | credencial não preenchida | veja `~/.francis/secrets/lupa/README.md` |
| `Acervo "X" não está em lupa.json` | acervo não cadastrado | adicione `nome` + `folder_id` ao config |
