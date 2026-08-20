---
name: lupa-buscar
description: >-
  Use SEMPRE que precisar encontrar imagens num acervo já indexado pelo lupa — "acha
  uma foto de X", "que referências temos de Y", "preciso de uma imagem em retrato sem
  texto", "o que tem no acervo sobre Z". Consulta o índice textual e devolve poucos
  candidatos com link e motivo, sem abrir nenhuma imagem. Use isto NO LUGAR de listar
  a pasta do Drive ou de olhar as imagens uma a uma — é a diferença entre gastar
  centavos e gastar dólares. NÃO use para criar ou atualizar o índice (skill lupa-indexar).
---

# lupa · buscar

## A regra que justifica esta skill

**Leia texto, nunca pixels.** Abrir imagem é a operação cara. O índice existe para
que você responda "que fotos servem aqui?" lendo linhas de texto. Só depois de a
busca reduzir o acervo a uma dúzia de candidatos é que vale olhar de fato — e aí
são doze imagens, não trezentas.

## Como consultar

**Com o MCP ligado** (o normal, pois o plugin o carrega sozinho):

```
lupa_search(consulta="pão forno luz quente", kind="foto", limite=10)
lupa_status()   # quais acervos existem e quando foram atualizados
```

**Pela linha de comando**, quando o MCP não estiver disponível:

```bash
python3 -m lupa search "ponte noturno azul" --kind peca --limite 10
python3 -m lupa status
```

## Os filtros que evitam lixo no resultado

O acervo mistura foto crua, post pronto e screenshot. Filtre por tipo, sempre:

| Filtro | Valores | Serve para |
|---|---|---|
| `kind` | `foto` `peca` `captura` `grafico` `logo` `outro` | separar matéria-prima de entrega pronta |
| `medium` | `fisico` `digital` `na` | `peca`+`fisico` = impresso, banner, mockup real |
| `orientation` | `retrato` `paisagem` `quadrado` | formato de destino |
| `has_text` | `true` `false` | `false` traz imagem limpa, sem tipografia embutida |

Exemplos que resolvem pedidos reais:

- *"fotos limpas para colocar texto por cima"* → `kind=foto`, `has_text=false`
- *"como já aplicamos a marca em impresso"* → `kind=peca`, `medium=fisico`
- *"referências de story"* → `orientation=retrato`, `kind=peca`

## Ler o resultado

Cada candidato traz descrição, tags, tipo, link e **por que casou** (`_casou por:`).
Use o motivo para calibrar: se casou só pelo OCR, a relação pode ser fraca — o texto
da peça mencionava o termo, mas a imagem talvez não mostre nada disso.

## Acervos de pasta local

Um acervo indexado a partir do disco não tem o OCR do Google. O campo `text` vem
vazio e a busca por texto embutido nas peças não funciona ali — busque por tags e
descrição. O `lupa_status` mostra quais acervos existem; o `INDEX.md` de cada um
mostra o vocabulário real.

## Quando a busca não acha nada

1. Rode `lupa_status` e veja o vocabulário real do acervo no `INDEX.md`.
2. Tente termos mais gerais — o índice usa palavras concretas, não conceitos
   ("madeira", "luz-natural"), não ("aconchegante", "premium").
3. Se o acervo estiver desatualizado, chame a skill `lupa-indexar` para rodar o
   `update` antes de concluir que a imagem não existe.
