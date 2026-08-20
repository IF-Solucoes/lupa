# lupa — índice de acervo visual para agentes

**Data:** 2026-08-20 · **Status:** design aprovado, aguardando implementação
**Módulo:** `lupa` (repositório público próprio, plugin instalável)

---

## 1. Problema

Um acervo de imagens no Google Drive é opaco para um agente. Para achar uma
referência, a IA precisa olhar as imagens — e olhar imagem custa caro. Com
centenas de arquivos, o custo inviabiliza o uso: foi exatamente o que aconteceu
ao tentar fazer curadoria de acervo dentro do Claude Cowork.

O acervo também é heterogêneo. Foto crua, post finalizado, mockup impresso e
screenshot convivem na mesma pasta. Sem separá-los, toda busca devolve lixo.

## 2. Objetivo

Um índice textual do acervo que qualquer agente leia barato, e que se mantenha
atualizado sem ser refeito.

Três verbos, e nada além disso:

| Verbo | Faz | Custo |
|---|---|---|
| `index` / `update` | são o mesmo comando: o lupa lê o índice e decide se é a primeira passada ou uma reconciliação | 1× por imagem, depois só o delta |
| `search` | consulta e devolve ≤15 candidatos com URL e motivo | zero |

O usuário nunca escolhe entre `index` e `update` — essa decisão é do programa.

## 3. Não-objetivos (a fronteira)

O lupa é infraestrutura sem opinião. Ele **não** sabe o que é cliente, marca,
identidade visual ou linha editorial. Quem julga adequação é a skill consumidora
— no caso do dono, uma skill editorial que já existe no Cowork.

Fora de escopo, deliberadamente:

- Julgar se uma imagem é boa, bonita ou adequada a uma marca.
- Vocabulário controlado global de tags.
- Embeddings e busca vetorial (CLIP). O índice textual resolve o caso de uso.
- Editar os arquivos do acervo. O lupa só cria os arquivos do próprio `_lupa/`.

> **Revisão de 2026-08-20:** pasta local voltou ao escopo, a pedido do dono. Ver
> a seção 5.5.

## 4. Achados que fundamentam o design

Quatro fatos verificados durante o desenho, cada um com consequência direta:

1. **O Drive já entrega OCR e labels, de graça.** O conector devolve, em
   `contentSnippet`, o texto extraído da imagem e uma lista `Image labels`.
   O OCR é excelente. Os labels são ruído genérico — num post sobre priorização,
   o Google sugeriu "Heineken" e "Beryllium".
   → *Consequência:* o VLM nunca paga por OCR nem por detecção de objeto. Ele
   preenche só o buraco: composição, paleta, luz, estilo.

2. **O conector do Drive não edita arquivos existentes.** Ele apenas cria
   arquivos novos numa pasta escolhida.
   → *Consequência:* o índice é **arquivo**, nunca metadado dos arquivos
   indexados. Isso também iguala as duas faces.

3. **Plugins do Claude Code carregam MCP nativamente**, via `.mcp.json` na raiz
   do plugin com `${CLAUDE_PLUGIN_ROOT}`. O cliente sobe e derruba o servidor
   stdio sozinho, em qualquer sistema operacional.
   → *Consequência:* o MCP viaja dentro do repositório. Ninguém precisa de WSL,
   porta, daemon ou instalação manual.

4. **Gemini 2.5 Flash-Lite descreve bem e julga mal.** Ele é feito para
   classificação e extração em volume, não para julgamento estético.
   → *Consequência:* duas passadas. A larga (Flash-Lite, centavos) cobre o
   acervo inteiro. A fina (o modelo da sessão do agente) olha só os 8–15
   finalistas que a busca trouxe.

## 5. Arquitetura

### 5.1 Duas faces, um contrato

- **Face Claude Code** — plugin com MCP embutido. Executa os três verbos.
  Faz o trabalho pesado: baixa miniaturas, chama o Gemini, escreve o índice.
- **Face Cowork / claude.ai** — `SKILL.md` que ensina a **ler** o índice pelo
  conector do Drive. Não executa código. É a face que a skill editorial consome.

O contrato entre elas são os arquivos do `_lupa/`. Nenhuma das faces conhece a
outra.

### 5.2 Layout do índice

Dentro da própria pasta do acervo, no Drive:

```
<acervo>/_lupa/
├── INDEX.md            # porta de entrada: contagens, vocabulário, como consultar
├── catalog.jsonl       # 1 linha por imagem — leitura de máquina
├── by-tag/<tag>.md     # índice invertido — leitura barata sem código
├── contact-sheets/     # grades visuais para curadoria humana
├── MANIFEST.json       # hashes e estado; é o que torna o update incremental
├── runs/<data>.md      # relatório de cada rodada
└── .backup/<ts>/       # índice anterior, antes de qualquer rebuild
```

Três níveis de leitura, do barato ao caro: `INDEX.md` (~2 KB, sempre) →
`by-tag/` (só as tags relevantes) → `catalog.jsonl` (só quando precisa cruzar).

O `INDEX.md` abre declarando a regra que sustenta a economia: **o agente lê
texto, nunca pixels.** Se quiser ver, vê os finalistas.

### 5.3 Schema da linha do catálogo (v1)

```json
{
  "id": "1a2B…",                    "file": "post-24-migracao.png",
  "url": "https://drive.google.com/…",
  "w": 1080, "h": 1350, "aspect": "4:5", "orientation": "retrato",
  "kind": "peca", "medium": "digital", "source": "gerado",
  "caption": "Ponte estaiada à noite, luz azul fria, silhueta urbana ao fundo",
  "tags": ["ponte", "noturno", "azul", "urbano"],
  "scene": "exterior", "people": 0,
  "palette": ["#0b1b2a", "#2f6f9f"],
  "has_text": true,
  "text": "MIGRAÇÃO — Adiar a modernização…",     // OCR, vem do Drive
  "labels": ["Bridge", "Technology"],             // labels do Drive, cruas
  "hash": "md5…", "model": "gemini-2.5-flash-lite", "v": 1
}
```

O contrato é versionado em `schema/index-v1.json`. Consumidor que quebra é
consumidor que ignorou a versão.

### 5.4 Classificação de tipo

Taxonomia **fechada** — taxonomia aberta é a própria poluição que queremos evitar:

- `kind`: `foto` · `peca` · `captura` · `grafico` · `logo` · `outro`
- `medium`: `fisico` · `digital` · `na`

Não existe `mockup`. Um mockup é `peca` + `medium: fisico`. A consumidora
decide se aquilo é entrega passada ou insumo para um render novo.

A classificação começa determinística, e o VLM só desempata:

| Sinal | Custo | Decide |
|---|---|---|
| EXIF (`Make`/`Model`) | zero | tem câmera → `source: camera`; não tem → `gerado` |
| Proporção | zero | 4:5, 9:16, 1:1 → peça de social; 3:2, 4:3 grande → foto |
| Densidade de OCR | zero | muito texto → `peca`/`grafico`; nenhum → `foto` |
| Formato | zero | PNG grande sem EXIF → export de design |
| VLM | já pago | `medium` (físico vs digital) e os casos ambíguos |

### 5.5 De onde vem o acervo — e por que isso ainda importa

O usuário aponta o acervo do jeito que for mais fácil: URL da pasta no Drive, id
solto, caminho no disco, ou o apelido de um acervo já indexado. O `lupa` resolve
sozinho; ninguém precisa saber o que é um `folder_id`, e ninguém edita config à mão
(a primeira rodada bem-sucedida cadastra o acervo).

A origem, porém, não é indiferente. Pela API do Drive vêm três coisas que o disco
não dá:

| | pasta no disco | API do Drive |
|---|---|---|
| descrever, classificar, buscar, incremental | idêntico | idêntico |
| OCR e labels de graça | não existem | vêm no metadado, custo zero |
| link do resultado | `file://…`, inútil fora da máquina | `https://…`, abre em qualquer lugar |
| identidade do arquivo | é o caminho: renomear força reindexar | `id` imutável |

O caso ambíguo é a pasta do **Google Drive for Desktop montada no disco**. Ela
parece local e é o Drive. O `lupa` detecta (`lupa/montagem.py`) e o pré-flight
explica o que se ganha ao fornecer a URL — **sem bloquear**. A escolha é informada,
não obrigatória.

### 5.6 O pré-flight é obrigatório

Não é uma flag, é a primeira etapa de toda rodada. Ele:

1. resolve o alvo e descobre o apelido real do acervo (o nome da pasta, não o id);
2. checa chave do Gemini, credencial do Drive, sessão de login e origem do acervo;
3. para em qualquer `✗`, **sem gastar nada**, imprimindo o passo a passo da correção;
4. roda o `--dry-run` e mostra o plano e o custo;
5. só então pergunta se prossegue.

A mensagem de erro é a documentação. Quem chama o `lupa` — pessoa ou agente —
recebe a instrução exata em vez de um traceback.

## 6. Atualização incremental

O `MANIFEST.json` guarda `id → hash` de tudo que já foi descrito. Cada `update`
lista os metadados do Drive (segundos, zero token) e reconcilia por conjuntos:

| Situação | Detecção | Ação | Custo |
|---|---|---|---|
| nova | `id` no Drive, ausente no manifesto | descreve | paga |
| alterada | `id` existe, `md5Checksum` mudou | redescreve | paga |
| sumida / lixeira | `id` no manifesto, ausente na listagem | remove a linha do catálogo | zero |
| intacta | `id` e hash iguais | pula | **zero** |

Rodar `update` duas vezes seguidas sem mudança no acervo não gasta nada.

Cada rodada escreve `runs/<data>.md`:

```
# Rodada 2026-08-20 14:32 · acervo "if-editorial"
Total: 3.412 imagens · indexadas: 3.412 (100%)
+ 40 novas · ~ 3 atualizadas · - 5 removidas · = 3.364 intactas (custo zero)
Custo: US$ 0,004 · duração: 1m18s · modelo: gemini-2.5-flash-lite
Falhas: 2 → runs/2026-08-20.errors.jsonl
```

## 7. Guarda-corpos

O verbo perigoso é o `index`. Ele se recusa a agir sobre um acervo já indexado:

```
✋ Este acervo já tem índice.
   3.412 imagens · última rodada 2026-08-18

   Você provavelmente quer:  lupa update
   Refazer custaria ~US$ 0,24 e apagaria 6 rodadas de histórico.
   Se é isso mesmo: lupa index --rebuild --confirm "if-editorial"
```

Quatro camadas, da mais barata à mais forte:

1. `index` detecta `MANIFEST.json` e desvia para `update`. Nunca sobrescreve.
2. Refazer exige digitar o nome do acervo: `--rebuild --confirm "<nome>"`.
   Não passa por engano nem por autocomplete de agente.
3. Todo rebuild copia o índice anterior para `.backup/<timestamp>/` antes de
   escrever. A operação é reversível.
4. Teto de custo: acima de `LUPA_CONFIRM_ABOVE` imagens novas (padrão 200), o
   comando mostra o plano e espera confirmação. `--dry-run` planeja sem gastar.

Um `.lock` em `_lupa/` impede que duas execuções simultâneas embaralhem o
manifesto. Lock velho (>30 min) é considerado órfão e liberado.

## 8. Credenciais e configuração

Segue o padrão `~/.francis` — segredo fora de qualquer repositório:

```
~/.francis/secrets/lupa/     (chmod 700)
├── README.md                # como obter cada credencial
├── lupa.env                 # GEMINI_API_KEY + freios (chmod 600)
├── google-oauth.json        # cliente OAuth baixado do Google Cloud
└── token.json               # nasce no primeiro login
~/.francis/config/lupa.json  # não-secreto: acervos (nome → folder_id)
~/.francis/state/lupa/       # cache local: miniaturas, manifesto espelhado
```

Escopos OAuth mínimos: `drive.readonly` para ler o acervo, `drive.file` para
criar e atualizar **apenas** os arquivos do próprio `_lupa/`.

## 9. Portabilidade

O repositório é público e não pode assumir o ambiente do autor:

- Nada de `powershell.exe`, `wslpath` ou caminho absoluto de WSL.
- `uv` como runtime (`uv run --script`, dependências declaradas no próprio
  arquivo via PEP 723). Funciona em Linux, macOS e Windows sem montar venv.
- O MCP é stdio, iniciado pelo cliente. Sem porta, sem daemon, sem serviço.
- A face Cowork não executa nada. Onde não há Python, o índice segue legível.

## 10. Estrutura do repositório

```
lupa/
├── plugin.json · .mcp.json         # o MCP viaja com o plugin
├── skills/
│   ├── indexar/SKILL.md            # index + update (face Code)
│   ├── buscar/SKILL.md             # search (face Code)
│   └── cowork/SKILL.md             # leitura do índice sem código
├── server/lupa_mcp.py              # MCP stdio: lupa_search, lupa_status
├── scripts/                        # pull · thumbs · caption · build · postcheck
├── schema/index-v1.json            # o contrato, versionado
├── exemplo/_lupa/                  # índice de brinquedo, para ver antes de rodar
├── docs/ · README.md · LICENSE (MIT)
```

## 11. Critérios de sucesso

O `postcheck.py` valida, e a entrega só fecha com todos verdes:

1. `index` num acervo novo produz `_lupa/` completo e válido contra o schema.
2. `index` num acervo já indexado **não escreve nada** e aponta para `update`.
3. `update` sem mudanças no acervo faz zero chamada ao Gemini.
4. `update` após adicionar, trocar e apagar arquivos reflete os três casos.
5. `search` responde em menos de 1 s sobre 10.000 linhas.
6. Um agente sem executar código responde "quais fotos em retrato, sem texto"
   lendo apenas `INDEX.md` e um arquivo de `by-tag/`.
7. Nenhum arquivo do acervo é modificado. Só o `_lupa/` é escrito.

## 12. Riscos conhecidos

Três pontos que só o primeiro acervo real confirma:

1. **Leitura do índice pelo conector.** A face Cowork depende de o conector do
   Drive ler `.md` e `.jsonl` como texto. É o comportamento esperado, mas vale
   validar antes de prometer a face — é o critério de sucesso 6.
2. **Busca dentro do catálogo, sem código.** O `search_files` do Drive não é
   confiável para filtrar linhas de um `.jsonl` grande. O `by-tag/` existe
   justamente para não depender disso.
3. **Batch API do Gemini exige projeto com faturamento ativo.** Sem isso, o
   `LUPA_BATCH=1` falha e o custo dobra no modo síncrono. O comando deve
   detectar e avisar, não falhar no meio da rodada.

## 13. Evoluções deixadas para depois

- Busca vetorial (CLIP) para consulta por semelhança visual.
- `changes.list` do Drive com `startPageToken`, no lugar da listagem completa.
- Fonte de acervo em pasta local ou S3.
