# lupa

**Índice de acervo visual para agentes de IA.** Transforma uma pasta de imagens do
Google Drive em texto pesquisável, para que um agente encontre a imagem certa **sem
abrir imagem nenhuma**.

```
$ lupa search "banner impresso azul" --kind peca --medium fisico

1 candidato (de 3.412 imagens):

- banner-evento.jpg [peca/fisico, paisagem] — Banner impresso em pé no estande,
  logo branco sobre azul, salão ao fundo
  tags: banner, evento, impresso, azul
  https://drive.google.com/file/d/d5/view
  casou por: tags:azul, tags:impresso
```

## O problema

Peça a uma IA para achar uma referência em 3.000 fotos e ela vai olhar as fotos. Cada
imagem custa tokens; três mil imagens custam caro o bastante para você desistir. Pior:
ela repete o gasto a cada nova pergunta.

O `lupa` inverte isso. Cada imagem é descrita **uma vez na vida**. Depois, todas as
perguntas são respondidas sobre texto.

## Como funciona

1. **Colhe o que já é de graça.** O Google Drive faz OCR das imagens e devolve isso
   nos metadados. O `lupa` aproveita — não paga por OCR.
2. **Decide o que der por metadado.** EXIF, proporção, formato e densidade de texto
   já dizem se algo é foto de câmera ou peça de design. Custo zero.
3. **Só então chama o modelo de visão**, e só para o que falta: composição, luz,
   paleta, estilo, tipo ambíguo. Gemini 2.5 Flash-Lite, em lote.
4. **Escreve um índice de texto** dentro da própria pasta do Drive (`_lupa/`), em três
   níveis de leitura, do barato ao caro.

Da segunda rodada em diante, só o que mudou custa alguma coisa.

### Pasta local e pasta do Drive não são a mesma coisa

Você pode indexar uma pasta do disco — inclusive a que o Google Drive for Desktop
sincroniza. Funciona, e o lupa detecta esse caso. Mas pela API do Drive você ganha
três coisas que o disco não dá:

- **o OCR que o Google já fez**, de graça — sem ele, o texto embutido nas peças
  não entra na busca;
- **links `https` compartilháveis**, que o Cowork e outras pessoas abrem;
- **o id imutável de cada arquivo** — renomear a pasta deixa de forçar reindexação.

Quando você aponta uma pasta montada, o pré-flight avisa e segue em frente. A
escolha é informada, não obrigatória.

## Instalação

```bash
git clone https://github.com/IF-Solucoes/lupa
cd lupa && python3 -m unittest discover -s tests   # 146 testes, sem rede
```

Como plugin do Claude Code, o servidor MCP sobe sozinho — ele não tem dependências,
só a biblioteca padrão do Python.

Para **indexar** (não para buscar) você precisa de:

- `pip install google-api-python-client google-auth-oauthlib`
- uma chave da [Gemini API](https://aistudio.google.com/apikey)
- um cliente OAuth de app-desktop do Google Cloud, com a Drive API ativada

Escopos usados: `drive.readonly` para ler o acervo e `drive.file` para escrever
**apenas** os arquivos que o próprio lupa cria. Ele nunca altera um arquivo seu.

## Uso

Aponte para o acervo do jeito que for mais fácil. O `lupa` entende os quatro:

```bash
python3 -m lupa index "https://drive.google.com/drive/folders/1a2B3c"   # URL do Drive
python3 -m lupa index 1a2B3c                                            # id da pasta
python3 -m lupa index ~/Fotos/Cliente                                   # pasta local
python3 -m lupa index if-editorial                                      # apelido, depois da 1ª vez
```

`index` e `update` fazem a mesma coisa: o lupa olha o índice e decide se é a
primeira rodada ou uma atualização. **Você não precisa escolher.**

### Toda rodada começa pelo pré-flight

Antes de gastar um centavo, o comando checa o ambiente, explica o que falta e
mostra o plano:

```
Pré-flight · acervo "if-editorial"

  ✓ acervo: pasta do Google Drive · id 1a2B3c · apelido "if-editorial"
  ✓ origem do acervo: pela API do Drive — com OCR e link compartilhável
  ✗ chave do Gemini: GEMINI_API_KEY está vazia
      Pegue uma chave em https://aistudio.google.com/apikey e escreva em
      ~/.francis/secrets/lupa/lupa.env    →    GEMINI_API_KEY=sua-chave
  ✓ estado do índice: já existe — será um update, só o que mudou custa

Plano desta rodada
  +40 novas · ~3 alteradas · -5 removidas · =3364 intactas
  imagens a descrever: 43
  custo estimado: menos de US$ 0.01
```

Com um `✗`, ele para e não gasta nada. Sem `✗`, ele mostra o plano e pergunta
antes de prosseguir. `--dry-run` para logo depois do plano; `--yes` não pergunta.

### Consultar

```bash
python3 -m lupa search "pão forno luz quente" --kind foto
python3 -m lupa status
```

## O índice

```
<acervo>/_lupa/
├── INDEX.md          # porta de entrada (~2 KB): contagens, vocabulário, como consultar
├── catalog.jsonl     # uma linha JSON por imagem — para filtrar por campo
├── by-tag/<tag>.md   # índice invertido, legível sem executar código
├── contact-sheets/   # grades visuais, para curadoria humana
├── MANIFEST.json     # hashes — é o que torna a atualização incremental
└── runs/<data>.md    # o que cada rodada mudou
```

Cada linha do catálogo segue [`schema/index-v1.json`](schema/index-v1.json):

```json
{"id":"d5","file":"banner-evento.jpg","url":"https://drive.google.com/…",
 "kind":"peca","medium":"fisico","source":"camera","orientation":"paisagem",
 "caption":"Banner impresso em pé no estande, logo branco sobre azul",
 "tags":["banner","evento","impresso","azul"],"has_text":true,
 "palette":["#052f41","#ffffff"],"hash":"…","v":1}
```

### A taxonomia é fechada de propósito

Taxonomia aberta vira poluição. São seis tipos e três materiais, e nada além:

| `kind` | | `medium` | |
|---|---|---|---|
| `foto` | fotografia capturada | `fisico` | impresso ou objeto real |
| `peca` | arte ou design finalizado | `digital` | arte de tela |
| `captura` | screenshot de tela | `na` | não se aplica |
| `grafico` | diagrama, gráfico, slide | | |
| `logo` | marca isolada | | |
| `outro` | nenhum acima | | |

Um mockup impresso é `peca` + `fisico`. Uma foto limpa para receber tipografia é
`foto` + `has_text: false`.

## As duas faces

- **Claude Code** — o plugin traz um servidor MCP (`lupa_search`, `lupa_status`) que
  sobe automaticamente. É onde a indexação acontece.
- **Cowork, claude.ai, qualquer agente com o conector do Drive** — lê os arquivos do
  `_lupa/` diretamente. Não executa nada, e não precisa. A skill `lupa-cowork` ensina
  o caminho: `INDEX.md` → `by-tag/` → candidatos.

O contrato entre as faces são os arquivos. Nenhuma delas conhece a outra.

## Custo

Descrever mil imagens em lote com Flash-Lite fica na casa de **centavos**. A conta
está em `lupa/caption.py` e aparece em todo `--dry-run` antes de você gastar.

Acima de 200 imagens novas, o comando pergunta antes de prosseguir.

## O que ele não faz

Não julga se uma imagem é boa, bonita ou adequada a uma marca. Não conhece cliente,
identidade visual nem linha editorial. Ele produz o índice; **quem tem gosto é quem
consome o índice**. Essa fronteira é deliberada.

Também não faz busca vetorial, não indexa pasta local e nunca modifica os arquivos
do seu acervo.

## Licença

MIT.
