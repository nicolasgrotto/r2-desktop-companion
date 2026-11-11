# Arquitetura multi-droides — evolução local 1.1.0

## Composição

`Companion` mantém uma instância de PetController, AnimationManager, Positioner,
BehaviorManager, ReactionDirector e AudioService. A garagem não cria outro mascote
nem outra máquina de estados. Produtividade, minigames, diagnóstico e updater
continuam utilizando os serviços anteriores.

`droids/profiles.py` define DroidProfile, DroidAudioProfile, DroidTheme e
DroidRegistry. O registro descobre `assets/droids/*/profile.json`, isola erros por
perfil e mantém o ID ativo. Carrega metadados na descoberta; pixmaps e bancos de
som são carregados somente para o ativo e para uma prévia solicitada.

`DroidController.prepare` valida novamente o arquivo, carrega clips e prepara
locomoção e áudio. `Companion.equip_droid` usa um gate temporário, preserva os
serviços e a posição, aplica recursos, preferências e tema, e grava. Preparação,
animação, tema ou gravação malsucedidos restauram o conjunto anterior. Só após
gravar o novo ID os recursos anteriores são liberados.

## Contrato de perfil

| Campo | Conteúdo |
| --- | --- |
| `profile_version` | 1 |
| `id`, `name`, `description` | ID estável e apresentação em texto simples |
| `manifest`, `renderer` | JSON de animações; `atlas` ou `layered` |
| `animations` | Mapa dos estados realmente presentes no manifesto para categorias |
| `audio` | Diretórios `voice`, `sounds` e mapeamento `phrases` por emoção |
| `personality` | `custom`, `calm`, `curious` ou `talkative` existentes |
| `movement` | Estratégia registrada em MOVEMENT_CONTROLLERS |
| `canvas`, `speed` | Dimensões lógicas e multiplicador de velocidade |
| `theme` | Nome, raio das bordas e 19 tokens de cores |
| `customization` | Opções efetivamente suportadas pelo renderizador |
| `art_status` | Estado real da arte, exibido na prévia e no diagnóstico |

Perfis com caminhos externos, arquivos ausentes, IDs duplicados, catálogos
inconsistentes, controladores não registrados ou temas inválidos são isolados.
Mesmo um perfil padrão inválido não impede os demais: o registro usa outro
perfil válido. Na inicialização, atlas ou PCM corrompidos também provocam fallback
sem apagar as preferências do personagem indisponível.
O catálogo corresponde exatamente ao manifesto. O PetController recusa estados
opcionais ausentes; o ReactionDirector filtra cenas por compatibilidade. IDLE é
obrigatório e serve como retorno seguro para transições essenciais.

## Recursos e animações

IDs distribuídos: `r2_default`, `dark_astromech` (Vesper), `spherical_droid` (Orbita).
Cada novo personagem possui `sprites/`, `animations/` e `audio/voice/`. O padrão
referencia o atlas legado diretamente, sem copiá-lo. Caminhos do perfil são
relativos a `assets`; imagens dos manifestos permanecem dentro do personagem.

| Personagem | Recursos | Organização |
| --- | --- | --- |
| Padrão | Atlas legado 256 × 1280 | Frames 64 × 64; 20 linhas; até 4 colunas; âncora (32,56) |
| Vesper | `sprites/vesper.png`, 384 × 1280 | Frames 64 × 64; 20 linhas; até 6 colunas; âncora (32,57); 110 frames |
| Orbita | `body.png`, 40 × 40; `head.png`, 30 × 18 | Canvas 64 × 64; centro do corpo (32,39); pivô da cabeça (32,19); 146 poses |

O manifesto v1 usa o carregador de atlas existente, com raiz explícita para
`animations/../sprites/`. Mantém limites de 256 frames, imagens até 2048 pixels,
32 MiB e loops apenas para IDLE/WALK/SLEEP. O manifesto v2 declara corpo e cabeça
uma vez e fornece poses com duration_ms, head_x, head_y, head_tilt, body_angle e
lift. DroidVisual passa pelo próprio AnimationManager; paint_visual desenha as
camadas. A rotação física afeta o corpo; a cabeça tem pivô e inclinação separados.
Escala usa nearest neighbor, sem esticar a resolução original para produzir assets.

`tools/generate_droids.py` é um gerador offline reproduzível de arte e sílabas
originais. Não é chamado pelo aplicativo. Não usa material extraído de franquias.
Vesper possui silhueta, painéis e atlas próprios; Orbita possui duas camadas reais.

**Arte:** o padrão continua provisório; os novos personagens têm pixel art original
procedural e aprovação artística final pendente. Para um redesenho de produção,
entregar as dimensões, transparência, pivôs e organização da tabela. Vesper precisa
das mesmas 20 linhas/110 frames para repouso, observação, inspeção, emoções, sono,
despertar, cumprimento, deslocamento, esforço e recuperação. Orbita precisa das
duas camadas independentes e das 146 poses registradas, sem achatamento. Conferir
contornos de um pixel, leitura a 64/160/256 DIP, paleta, recorte e loops antes de
substituir os PNGs. Não há promessa de arte HD final.

## Locomoção

Positioner continua responsável por monitores, área disponível, clamp, posição
normalizada, arrasto e cantos. Recebe uma estratégia `movement`.
DroidMovementController mantém a locomoção astromecânica compartilhada pelo
padrão e Vesper. Vesper usa velocidade 0,8 e a personalidade Calm existente.

SphericalMovementController aplica smoothstep à aceleração/desaceleração,
calcula rotação por `graus(dx/raio)` com raio proporcional ao tamanho visual,
limita inclinação da cabeça e amortece seu retorno. Arrastar informa deslocamento;
soltar preserva a inclinação inicial e recupera equilíbrio. O timer de resposta
de 33 ms para ao estabilizar. Gates de tela cheia/ocultação/sessão interrompem a
resposta. A janela inteira não gira. A política de cantos permanece a anterior.

Novo tipo de locomoção: implementar progress, displaced, release, stop e close;
registrar a classe em MOVEMENT_CONTROLLERS; declarar a chave no perfil. A estratégia
não escolhe estados nem geometria de monitores. Timers próprios param em stop/close.

## Áudio

O único AudioService prepara e ativa bancos e libera o anterior. Pode manter uma
prévia adicional. Cada banco tem 15 efeitos compartilhados e 30 frases compostas
pelo mecanismo existente: 45 QSoundEffects. Vesper e Orbita têm 12 sílabas PCM
próprias cada, sintetizadas localmente. Vesper usa frequências graves/envelopes
mais lentos; Orbita usa frequências agudas e sílabas curtas. Seus mapas diferem.

PCM é validado antes da troca: mono, 16 bits, 22050 Hz, duração limitada e dados
completos. Cache temporário de frases é removido ao liberar o banco ou encerrar.
Qt carrega os efeitos assincronamente; preparação não afirma audibilidade física.

Master é global; volume, mute, categorias e intervalos são individuais. Prévias
usam o mesmo reprodutor e cooldowns, respeitando master, mute ativo, contexto,
silêncio e categorias. Só uma voz toca. Equipar interrompe reprodução residual;
mudar a prévia libera seu banco. Não há alteração no volume do Windows.
Antes de destruir QSoundEffects, a fonte é removida; a saída também libera o banco
ativo e desconecta os sinais dos monitores. Inscrições de tema de janelas encerradas
são removidas. Os testes drenam DeferredDelete entre casos, mantendo a verificação
de exceções em callbacks durante a destruição.

## Identidade visual e interfaces

ThemeManager adapta os estilos existentes, reaplica widgets registrados, paleta
e ícones. Pinturas de temporizador, favoritos, roda e hologramas consultam tokens.
Os 19 tokens cobrem cores primária/secundária/destaque, fundo/painel/borda, textos,
hero e seus textos, seleção, foco, texto de botão, erro, desabilitado, notificação,
holograma e decoração. Os pares de leitura são validados para contraste ≥ 4,5:1.
Títulos usam texto, garantindo leitura no fundo escuro.

Padrão: branco/azul/cinza. Vesper: grafite/bronze/vermelho/âmbar, contornos mais
retos. Orbita: branco/laranja/cinza quente, bordas mais arredondadas. Configurações,
Ferramentas, tarefas, notas, diagnóstico, minigames, favoritos, menus, balões e
Central de Áudio acompanham o equipado. Garagem e galeria usam um override local
do tema selecionado para prévia, sem mudar o tema global.

A Central de Atualização continua em processo separado. Um watcher de leitura
observa o ID persistido a cada 750 ms, atualiza tema e personagem do cabeçalho,
sem assumir o lock ou escrever configurações. Consulta/download/SHA-256/instalação/
backup/reinício continuam nos componentes anteriores.

Garagem e Galeria compartilham DroidStudio e um AnimationManager de prévia.
Ocultar/fechar interrompe timers e libera clips. Garagem oferece destaque,
descrição, equipado, categorias, sequência/frame, voz de demonstração,
personalidade, personalização e restaurar padrão. Apenas Equipar grava e altera
o mascote. A Galeria oferece categorias reais, anterior/próxima, reprodução,
repetição, parada e frames. A prévia de rolagem anima as camadas independentes.

Central de Áudio oferece comparação de personagens, dez emoções, quinze efeitos,
variantes com sílabas, volume, mute, categorias, master explícito e Salvar.
Salvar áudio de personagem inativo não o equipa. As três janelas estão no menu.
Áreas roláveis mantêm os controles acessíveis em áreas de trabalho pequenas;
há cobertura específica para janelas de 480 × 360 DIP.

Personalizações: quatro cores legadas do padrão; iluminação âmbar/vermelha de
Vesper; iluminação âmbar/vermelha e centelha de Orbita. Não há acessórios de
outros tipos. Restaurar padrão afeta o rascunho individual até Equipar.

## Persistência e migração

Schema 1 recebe active_droid e droid_preferences aditivos. Cada entrada guarda
behavior, audio, personality, appearance e customization. Campos legados projetam
as preferências do equipado para manter interfaces compatíveis. ConfigStore
sincroniza essa projeção sem modificar o objeto fornecido pelo chamador.

Configuração antiga pertence ao padrão. Outros personagens recebem defaults
próprios. Favoritos, posição, quiet hours, startup, updater e master permanecem
globais; tasks/notes continuam em tools.json. QSaveFile, backup, lock, debounce,
recuperação de corrupção e proteção de schema futuro foram preservados. Personagem
removido causa fallback e mantém suas preferências para instalação posterior.

## Adicionar um personagem

1. Criar pasta em assets/droids com ID estável e recursos originais.
2. Usar um perfil existente como contrato e alterar apresentação, recursos,
   personalidade, áudio, tema e personalizações suportadas.
3. Criar manifesto v1/v2; declarar apenas animações presentes.
4. Validar caminhos, PCM, limites de imagens/frames e contraste; declarar uma
   estratégia de locomoção registrada ou implementar uma conforme o contrato.
5. Executar testes de perfil/troca/falha/prévia/persistência e abrir a garagem.
6. Fazer build e smoke no EXE. O spec inclui assets recursivamente.

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp .runtime-tests-multidroid
.\.venv\Scripts\python.exe tools\verify_multidroid.py
.\.venv\Scripts\python.exe tools\build_windows.py --artifact-label multidroid
.\dist\1.1.0-multidroid\R2Companion\R2Companion.exe --data-dir .runtime-exe-multidroid --smoke-test --smoke-droids
```

O rótulo separa o build de dist/1.1.0 e do ZIP anterior. A versão permanece 1.1.0.
Nenhuma tag, release ou publicação é criada automaticamente.
