# Relatório da evolução multi-droides — 12/11/2026

## A. Resumo

Implementação integrada ao repositório mantendo a versão **1.1.0** e seu diretório
de dados. Droid Garage, Central de Áudio, Galeria de Animações, três perfis, troca
sem reinício, preferências individuais, temas completos e locomoção esférica estão
implementados. A arte nova é original e procedural; sua aprovação artística final
permanece pendente. Não houve publicação, tag, instalação automática ou alteração
nos artefatos anteriores.

## B. Arquitetura

DroidProfile/DroidRegistry descrevem e descobrem recursos, animações, áudio,
personalidade, movimento, dimensões, velocidade, temas e personalizações.
DroidController prepara recursos antes de aplicar a troca. PetController continua
sendo a única máquina de estados; AnimationManager, Positioner, BehaviorManager,
ReactionDirector e AudioService são os serviços existentes.

A troca usa um gate temporário e restaura o conjunto anterior se preparação,
animação, tema ou gravação falharem. Perfis inválidos são isolados; recursos
corrompidos na inicialização permitem fallback sem apagar preferências.
Detalhes e contratos: [MULTI_DROID_ARCHITECTURE.md](MULTI_DROID_ARCHITECTURE.md).

## C. Personagens

| Personagem | Aparência e animações | Voz, personalidade e locomoção |
| --- | --- | --- |
| R2 · Original | Atlas anterior preservado, 20 estados, quatro cores | Sílabas/frases anteriores; preferências migradas; movimento astromecânico |
| Vesper | Atlas próprio grafite/bronze, 20 estados/110 frames | 12 sílabas graves próprias, 30 frases; Calm; movimento compartilhado com velocidade 0,8 |
| Orbita | Corpo 40 × 40 e cabeça 30 × 18 independentes; 20 estados/146 poses | 12 sílabas agudas próprias, 30 frases; Curious; estratégia esférica própria |

Orbita calcula rotação pelo deslocamento horizontal, usa aceleração/desaceleração
suaves e mantém a cabeça em pivô independente. Arrasto produz resposta corporal e
recuperação amortecida da cabeça. Os limites, monitores, cantos e gates continuam
sob responsabilidade dos componentes anteriores.

## D. Identidade visual

Temas usam 19 tokens e raios de borda próprios: branco/azul, grafite/bronze/vermelho/
âmbar e branco/laranja. Estilos, paleta, ícones e pinturas existentes foram
adaptados: configurações, ferramentas, áudio, tarefas, notas, diagnóstico,
minigames, favoritos, menus, roda, balões, notificações e hologramas.

Garagem e galeria possuem tema local de prévia. A central de atualização mantém
seu processo separado e acompanha o ID persistido por leitura a cada 750 ms.
Pares de texto/fundo têm validação de contraste mínimo 4,5:1; o contraste dos títulos
escuros também tem regressão específica. As interfaces anteriores não foram refeitas.

## E. Droid Garage

Seleção, destaque, equipado, descrição, tema, categorias de animação, frames,
vocalização de demonstração, personalidade, personalizações e restauração do padrão.
Prévia usa recursos separados e não altera o mascote ou os dados. Equipar aplica
e persiste sem reiniciar. Falhas mantêm o personagem anterior. Configurações abertas
são fechadas após uma troca bem-sucedida para evitar salvar um rascunho de outro droide.

## F. Central de Áudio e Galeria

Central de Áudio: dez emoções, três variantes por emoção, quinze efeitos,
comparação entre personagens, volume, mute, categorias e master explícito.
Salvar preferências de áudio de um inativo não o equipa. Um único reprodutor
mantém cooldowns e contexto; prévias não sobrepõem vozes.

Galeria: catálogo do manifesto, categorias, anterior/próxima, reproduzir, repetir,
parar e frames individuais. A prévia de rolagem anima corpo e cabeça separadamente.
Ocultar a prévia interrompe timers e libera os clips. As três novas janelas usam
áreas roláveis, com teste de acesso aos controles em 480 × 360 DIP.

## G. Personalização

Original: azul, verde oceano, violeta e âmbar. Vesper: iluminação âmbar/vermelha,
aplicada aos pixels do LED em cada frame. Orbita: iluminação âmbar/vermelha e
centelha decorativa. Opções são declaradas por perfil; não há acessórios de outros
tipos, moedas ou desbloqueios. Restaurar padrão afeta o rascunho até Equipar.

## H. Persistência

Schema 1 aditivo recebe active_droid e droid_preferences. O padrão herda os dados
anteriores; novos personagens recebem seus próprios defaults. Volume, categorias,
personalidade, comportamento, aparência e personalizações são individuais.
Master, silêncio programado, posição, favoritos, sistema e updater continuam globais.
Tarefas/notas continuam em tools.json. Foram preservados QSaveFile, backup, lock,
debounce, recuperação de corrupção e proteção de schema futuro.

## I. Desempenho

Medições de 15 s por personagem, quatro CPUs lógicas; percentual normalizado
pela capacidade total da máquina. A primeira fase inclui a reação inicial.

| Personagem | CPU média inicial | CPU média em atividade | CPU média oculto | Pico de working set |
| --- | --- | --- | --- | --- |
| Original | 0,20% | 0,08% | 0,07% | 86,2 MiB |
| Vesper | 0,58% | 0,00% | 0,13% | 90,5 MiB |
| Orbita | 0,29% | 0,55% | 0,19% | 88,6 MiB |

São amostras curtas, sujeitas à granularidade do contador de CPU do Windows;
0,00% em uma fase não demonstra custo nulo. Todas encerraram com zero timers
centrais ativos e timer de movimento parado.

No ensaio das interfaces, 18/18 trocas foram aceitas, sem exceções de callback.
Tempos entre 392 e 1.055 ms; working set entre 161,3 e 166,2 MiB com as interfaces
carregadas. Após liberar os anteriores, cada troca manteve 45 objetos de áudio.
O deslocamento de Orbita produziu rotação corporal observável no event loop real.
Os testes confirmam que a rotação do corpo não gira a cabeça.

Esses ensaios não substituem avaliação prolongada de consumo e estabilidade.

## J. Testes

**294 testes aprovados em 136,36 s**, incluindo os 237 anteriores e 57 novos.
Nenhum teste removido, desabilitado ou marcado com skip.

Cobertura nova: perfis/recursos inválidos, padrão e fallback, troca/rollback,
persistência/migração/corrupção/reabertura, preferências independentes, temas e
contraste, prévias, catálogo, PCM inválido, políticas sonoras, liberação de recursos,
componentes independentes, rotação, aceleração/desaceleração, cabeça, arrasto,
recuperação, limites, tela cheia e integração de diagnóstico/cenas/hologramas.

Durante a integração houve abortos nativos ao processar uma fila acumulada de
DeferredDelete entre testes Qt. A fixture agora processa essas destruições em
cada teardown, mantendo a captura de exceções em callbacks. O conjunto de 62 testes
de droides/updater passou junto nesse diagnóstico; depois a suíte integral passou
com as verificações finais. Também foram corrigidas a liberação de áudio, a
desconexão dos sinais de monitores e a remoção de inscrições de tema encerradas.

Log final: `.runtime-tests-multidroid-complete.log`.

## K. Build

PyInstaller concluído com saída 0. Pacote em
`dist/1.1.0-multidroid/R2Companion/R2Companion.exe` e ZIP separado
`dist/R2Companion-Windows-x64-multidroid.zip`, com **58.826.863 bytes**.

Integridade ZIP verificada; 284 arquivos, incluindo três perfis, três PNGs novos e
24 WAVs novos, além de todos os recursos anteriores. SHA-256:

```text
6572c5e0f21b11a5e95efd3627aee3487e43c5f34c61abacc08a4e98365095e2
```

O rótulo multidroid mantém dist/1.1.0 e o ZIP anterior preservados. O spec existente
já inclui assets recursivamente. Log: `.runtime-build-multidroid-complete.log`.

O próprio EXE foi iniciado com dados isolados e `--smoke-test --smoke-droids`:
equipou os três personagens, registrou os controladores/perfis corretos e encerrou
com zero timers centrais ativos e timer de movimento parado. Ambiente observado:
um monitor físico, 1440 × 860 DIP de área útil, DPR 1,0.

No ensaio sonoro, os 45 efeitos de cada banco chegaram a Ready e a reprodução foi
aceita e indicada como isPlaying a 5% de volume. Isso valida o backend Qt no
ambiente disponível; a audibilidade e qualidade física não foram afirmadas.

## L. Principais arquivos

| Grupo | Arquivos |
| --- | --- |
| Perfis e controle | src/r2_companion/droids/{profiles,preferences,controller,movement,visuals,themes}.py |
| Integração | app.py; core/config.py; pet/{animation,controller,positioning,reactions,window}.py |
| Áudio | services/{audio,vocalizations,storage}.py; assets/droids/*/audio/voice |
| Interfaces | ui/droids.py e adaptações de theme, bubble, context_menu, productivity, radial, settings, targets, tools e updates |
| Arte e perfis | assets/droids/*; tools/generate_droids.py; assets/LICENSES.md |
| Validação | tests/test_droids.py; tests/conftest.py; tools/verify_multidroid.py; tools/profile_companion.py |
| Build e documentação | tools/build_windows.py; README.md; MULTI_DROID_AUDIT.md; MULTI_DROID_ARCHITECTURE.md; este relatório |

O ARCHITECTURE.md local, não rastreado no início, permanece intacto e fora dos commits.

## M. Commits

| Hash | Mensagem | Horário real, America/Sao_Paulo |
| --- | --- | --- |
| f0c442c | feat(droids): add profiles original characters and spherical locomotion | 12/11/2026 14:37:30 −03:00 |
| 9e52370 | feat(ui): integrate Droid Garage audio center and dynamic themes | 12/11/2026 14:48:37 −03:00 |

O commit que introduz este relatório reúne validação, robustez e documentação.
Seu hash e horário constam da resposta final e podem ser consultados com:
`git log -1 --format="%h %ai %s" -- MULTI_DROID_REPORT.md`.
As datas não foram retroativas: são horários reais de execução em 12/11,
posteriores ao commit-base de 10/11 às 11:25, com intervalos de 10–45 minutos.

## N. Pendências reais

- Aprovação artística final dos desenhos procedurais; o padrão permanece provisório.
  Dimensões, atlas, camadas, pivôs e frames necessários a um redesenho de produção
  estão especificados na documentação de arquitetura.
- Audibilidade e qualidade subjetiva em alto-falantes/fones não são comprovadas por
  QSoundEffect Ready/isPlaying. As limitações físicas serão mantidas nas evidências.
- Avaliação prolongada, múltiplos monitores físicos e combinações de DPI diferentes
  precisam da validação manual abaixo. A geometria simulada continua coberta.

## O. Checklist manual no Windows

- [ ] Executar a pasta completa do build separado e alternar pelos três personagens.
- [ ] Conferir silhueta, recorte, nitidez e leitura em 64/160/256 DIP.
- [ ] Ouvir vozes e efeitos em saída real; comparar volume, mute, categorias e cooldowns.
- [ ] Arrastar Orbita em ambas as direções e conferir rotação, cabeça e recuperação.
- [ ] Alternar monitores com posições negativas, DPI 100/125/150/200% e desconexão de tela.
- [ ] Verificar cantos manuais, tela cheia, silêncio programado, inatividade e pass-through.
- [ ] Conferir temas em áudio, ferramentas, tarefas/notas, minigames, diagnóstico,
  configurações, roda, menus, notificações e central de atualização aberta.
- [ ] Reabrir o aplicativo e conferir personalidade, iluminação e áudio de cada droide.
- [ ] Exercitar tarefas, notas, temporizador, favoritos e Duel of Fates.
- [ ] Manter execução prolongada e observar memória/CPU e disponibilidade da bandeja.

## Evidências locais

- `.runtime-multidroid-delivery-review/report.json` e PNGs de garagem, áudio,
  galeria, desktop, ferramentas, configurações e updater para cada personagem.
- `.runtime-profile-multidroid-r2_default/profile.json`.
- `.runtime-profile-multidroid-dark_astromech/profile.json`.
- `.runtime-profile-multidroid-spherical_droid/profile.json`.
- `.runtime-exe-multidroid-final/smoke.json` e capturas do executável.
- `.runtime-multidroid-delivery-validation.log`.
