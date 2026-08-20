---
name: lupa-indexar
description: >-
  Use quando o usuário quiser CRIAR ou ATUALIZAR o índice de um acervo de imagens —
  "indexa essas fotos", "cataloga essa pasta", "atualiza o índice", "o que mudou nas
  referências". O acervo pode ser dito de qualquer jeito: URL de pasta do Google Drive,
  id da pasta, caminho de uma pasta local, ou o apelido de um acervo já indexado. Toda
  rodada começa por um pré-flight que checa o ambiente, ensina o que falta e mostra o
  custo antes de gastar. Incremental: só o que mudou custa. NÃO use para buscar no
  índice (skill lupa-buscar) nem para julgar se uma imagem serve a uma marca.
---

# lupa · indexar

## O que esta skill faz

Transforma uma pasta de imagens num índice de texto, para que agentes encontrem
referências **sem abrir as imagens**. Cada imagem é descrita uma vez na vida.

**Ela não tem opinião.** Não sabe o que é cliente, marca ou linha editorial. Quem
julga adequação é a skill consumidora.

## Um comando, e o usuário não precisa saber de nada

```bash
python3 -m lupa index <alvo>
```

O alvo pode ser qualquer uma destas formas — não pergunte ao usuário qual delas
ele tem, apenas passe o que ele disser:

| O usuário disse | Exemplo |
|---|---|
| a URL da pasta no Drive | `https://drive.google.com/drive/folders/1a2B3c` |
| o id da pasta | `1a2B3c` |
| um caminho no disco | `~/Fotos/Cliente` ou `/mnt/g/Meu Drive/Clientes` |
| o apelido de um acervo já indexado | `if-editorial` |

`index` e `update` são o mesmo comando. O lupa olha o índice e decide se é a
primeira rodada ou uma atualização. **Nunca pergunte ao usuário qual usar.**

## O pré-flight roda sempre — leia o que ele diz

Antes de qualquer gasto, o comando imprime o diagnóstico e o plano:

- **`✗` (bloqueio)** — ele parou e não gastou nada. A própria mensagem traz o passo
  a passo da correção. **Repasse ao usuário exatamente essa instrução**, não invente
  outra.
- **`!` (aviso)** — segue funcionando. O caso mais comum: a pasta apontada é o Drive
  montado no disco. Vale mencionar ao usuário o que ele ganharia colando a URL do
  Drive (OCR de graça, link compartilhável, id estável), sem obrigá-lo a mudar.
- **Plano** — quantas imagens serão descritas e o custo. Se disser "Nada mudou",
  a rodada acabou ali: relate isso e pare.

Para ver só o plano, sem executar: `--dry-run`.
Para rodar sem interação (agente autônomo): `--yes` — mas só depois de ter lido o plano.

## Depois da rodada

O comando salva o acervo com um apelido (tirado do nome da pasta), publica o índice
no Drive quando a origem é o Drive, e imprime o resumo. Relate ao usuário o que mudou
(`+N novas · ~N alteradas · -N removidas`) e o custo. Se houver falhas, elas estão em
`runs/<data>.errors.jsonl`.

## Refazer do zero (raro, e caro)

```bash
python3 -m lupa index <apelido> --rebuild --confirm "<apelido>"
```

Exige digitar o apelido. O índice anterior vai para `.backup/` antes de qualquer
escrita. Só faça se o schema mudou ou o índice corrompeu.

## Erros comuns

| Sintoma | Saída |
|---|---|
| `✗ chave do Gemini` | siga a instrução impressa; a chave vai em `~/.francis/secrets/lupa/lupa.env` |
| `✗ acesso ao Google Drive` | falta o `google-oauth.json`; a mensagem traz os 3 passos |
| `Não entendi "<x>"` | o alvo não é URL, id nem pasta existente — peça a URL da pasta ao usuário |
| `⏳ Outra execução está usando este índice` | espere, ou apague `_lupa/.lock` se tiver certeza |
