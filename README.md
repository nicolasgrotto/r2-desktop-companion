# R2 Desktop Companion

Mascote desktop local para Windows 10/11, em Python/PySide6. Robô branco e azul com
janela transparente, animações por atlas/PNG e peças articuladas.
**Não utiliza IA, backend, modelos locais ou telemetria.** O mascote funciona
offline; somente o atualizador manual consulta o GitHub por solicitação do usuário.

Os personagens usam arte original em pixels; os recursos dos modelos anteriores
permanecem preservados.
O Companion é independente do casemod e não executa nem altera seus scripts de som.

**Versão 1.2.0:** a Droid Garage reúne sete companheiros. Lumo equilibra-se em
uma roda, Vigia flutua com sensores e manipuladores independentes, Pico caminha
com pernas articuladas e cabeça binocular expressiva, e Tranco usa tração própria
e braços retráteis. Sono, projeção do timer e ferramentas continuam disponíveis.
Novidades no [changelog](packaging/docs/CHANGELOG.md).

A reação por CPU exige **90%**, com leitura a cada 15 segundos e intervalo mínimo
de cinco minutos. Requer reações do sistema habilitadas, autonomia disponível e
droide em repouso; não mede temperatura física.

Equipe R2, Vesper (grafite/bronze), Orbita (esférico branco/laranja), Lumo,
Vigia, Pico ou Tranco sem reiniciar. Cada um tem voz, personalidade,
personalizações e tema próprios. A seleção e as preferências individuais são
salvas automaticamente e mantidas ao reiniciar ou atualizar.
Orbita rola com corpo e cabeça independentes. O Droid Garage permite explorar
categorias, reproduzir, repetir, parar e inspecionar frames sem alterar o personagem
ativo. A Central de Áudio mantém as preferências de cada personagem.
Tarefas, notas, favoritos e configurações anteriores continuam compatíveis.

Consulte a [arquitetura](ARCHITECTURE.md).

## Executar pelo código

Notas da release: [Changelog](packaging/docs/CHANGELOG.md) e [1.2.0](packaging/docs/release-notes/v1.2.0.md).

Requer Python 3.12+ x64. Combinação exercitada: Python 3.13.12 e Qt/PySide6 6.10.2
no Windows 10 22H2. Abra PowerShell na raiz deste repositório:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-cache-dir -r requirements.txt
.\.venv\Scripts\python.exe run_companion.py
```

Não é necessário ativar o ambiente virtual, instalar globalmente ou executar como administrador.
As dependências são baixadas na instalação; a aplicação funciona offline.
Para isolar os dados dentro do projeto:

```powershell
.\.venv\Scripts\python.exe run_companion.py --data-dir .runtime-manual
```

## Usar

- Clique esquerdo: reação, fala e roda de ações essenciais. Na primeira camada, use o centro para fechar; nas demais, ele retorna à camada anterior. Esc ou × fecham a roda; clicar fora também fecha. Arraste com o botão esquerdo para reposicionar — o balão acompanha o personagem.
- Botão direito: Interagir, Aplicativos, Atalhos, Ferramentas, Configurações e Sair.
- Na roda, Ferramentas abre uma segunda camada com Central de ferramentas, Relógio, Temporizador, Sistema, Tarefas e Anotações.
- Ferramentas: relógio/data em destaque, temporizador com minutos/segundos e atalhos de 1/5/25 minutos, CPU/RAM e bateria quando disponível.
- Ferramentas → Minigames: catálogo com Duel of Fates. Jogar abre `https://nicolasgrotto.github.io/duel-of-fates/` via QDesktopServices/QUrl no navegador padrão. Não há navegador incorporado, WebEngine ou download do jogo pelo Companion. Para ampliar o catálogo, acrescente um Minigame em `features/minigames.py`.
- Ferramentas → Diagnóstico: mostra personagem, versão, sistema, CPU, memória, bateria e áudio sob demanda. A página possui rolagem e a central permanece dentro da tela.
- Segure o botão esquerdo sobre a cabeça por 650 ms para fazer carinho. Arrastar cancela o carinho; a reação não abre a roda de ações.
- Tarefas: adicionar, concluir, reabrir, filtrar pendentes e excluir. Notas: criar, editar, excluir e copiar, com salvamento automático local. Ambas também estão no menu de contexto.
- Depois de três minutos contínuos dormindo, o droide só acorda com um clique nele. Esse clique reproduz o despertar sem abrir a roda; um sono curto ainda pode terminar automaticamente quando você voltar.
- Na transmissão e nas preferências, o nome acompanha o personagem equipado. A reação de aquecimento por CPU elevada inclui fumaça animada.
- Clique duplo: cumprimento. Cliques repetidos: confusão. Arrasto: esforço e recuperação. Bateria baixa, carregamento e CPU elevada podem gerar reações discretas com cooldown.
- Na roda, Configurações → Aplicativos e Meus locais abrem painéis com busca e seleção. Use Gerenciar favoritos para editar destinos. Configurações → Autonomia reúne Explorar e Pausar/Continuar. Explorar inicia um passeio quando houver espaço.
- Configurações: tamanho, frequência, caminhada, inatividade, som, balões, prioridade da janela, aplicativos e locais favoritos.
- Áudio: habilite Efeitos sonoros do R2 em Preferências; ajuste volume, modo silencioso, intervalo e categorias na aba Áudio. O som começa desativado e não modifica o volume do Windows.
- Personalidade: Calmo, Curioso e Comunicativo ajustam pesos, frequência e vocalizações. O perfil não liga o som nem altera seu volume ou modo silencioso. As preferências continuam ajustáveis.
- Aparência: detalhes em azul original, verde oceano, violeta ou âmbar. Projetar → Relógio ou Horário e data mantém uma projeção com conteúdo atualizado. A projeção flutua acima do personagem, ou abaixo quando faltar espaço, com feixes holográficos saindo do olho. Use Encerrar projeção para removê-la. A opção Permitir projeções holográficas nas Configurações controla sua disponibilidade.
- Horário de silêncio: use horas locais em HH:mm; é possível atravessar a meia-noite. Início e fim iguais significam silêncio o dia inteiro. Durante o período, autonomia, sons e avisos ficam suspensos; ferramentas continuam disponíveis.
- Para adicionar um aplicativo/pasta/arquivo, use a aba Aplicativos e atalhos. Selecione um destino e use Criar atalho para um nome adicional no menu Atalhos.
- Somente `.exe` local sem argumentos; scripts e interpretadores conhecidos são bloqueados. Arquivos favoritos: TXT, PDF, PNG, JPG/JPEG, WAV e MP3. Pastas locais também são aceitas. Não importamos `.lnk`/`.url` nem comandos.
- Bandeja: botão direito abre o mesmo menu; clique simples mostra o mascote; clique duplo abre Ferramentas.
- Pausar autonomia preserva interações e o temporizador. Desativar Caminhar sozinho permite expressões sem deslocamento.
- Deixar cliques atravessarem o mascote é temporário e reversível pelo menu da bandeja. Ocultar e atravessar cliques são desabilitados sem bandeja; se ela desaparecer, o mascote volta a ser acessível.
- Restaurar posição retorna a uma área segura do monitor principal. Mover para monitor escolhe outra tela explicitamente.
- Sair encerra todos os timers, som, bandeja e bloqueio de configuração. Fechar Ferramentas/Configurações não encerra o mascote.

Com Caminhar sozinho habilitado e frequência Normal, o primeiro passeio começa
em aproximadamente 15–25 segundos de disponibilidade; os próximos ficam separados
por 75–120 segundos. No modo Discreto, o intervalo entre passeios é 150–240 segundos.
Sono, arraste, menus, Configurações e a roda aberta suspendem a autonomia. Interações
reservam uma pausa antes de voltar a caminhar. Nas bordas ele tenta a direção oposta.
A roda fecha após 12 segundos sem uso; ao apontar para ela esse prazo é suspenso,
e ao sair com o ponteiro ela fecha em seis segundos. Assim ela não prende a autonomia
indefinidamente. Caminhadas permanecem curtas e dentro do monitor atual. Se o personagem cobrir a janela em uso, incluindo a Central de Ferramentas, ele caminha para a borda livre mais próxima. O desvio respeita pausa, sono, silêncio e a opção Caminhar sozinho; janelas maximizadas seguem a política de tela cheia existente.

Ao aproximar o cursor, o R2 pode olhar ou demonstrar curiosidade. Se o ponteiro
ficar parado, pode se aproximar devagar, mantendo distância; não há perseguição
contínua. O personagem também pode inspecionar o ambiente, aparentar trabalhar,
comemorar e retornar à posição em que foi colocado manualmente.

Arraste o R2 até um canto e solte para guardar essa preferência. Em tela cheia,
o modo Automático mantém o personagem silencioso nesse canto; sem canto escolhido
no monitor atual, oculta temporariamente. Passeios e balões ficam suspensos.
Configurações permite sempre ocultar, usar o canto ou ficar discretamente na
posição atual. Restaurar posição limpa a preferência manual de canto.

O temporizador pode pausar, continuar e reiniciar. Continua com o robô dormindo,
oculto ou com autonomia pausada. O tempo de suspensão do computador conta;
conclusões vencidas são processadas uma vez após retomar. Sair da aplicação
encerra a contagem: restaurar temporizadores entre execuções não é suportado.
Uma conclusão permanece indicada em Ferramentas, mesmo se o Windows ocultar o aviso.
Os avisos visuais da bandeja usam um pequeno balão Qt, sem som próprio; o áudio
passa pelo AudioService e respeita volume, silenciamento e categorias. Tela cheia
e suspensão ocultam esses avisos também.

## Dados e inicialização automática

As vocalizações combinam 12 sílabas originais em três frases para cada uma de dez
emoções. O cache temporário é criado ao iniciar e removido ao encerrar. Há somente
uma voz ativa, respeitando os intervalos globais e de categoria. Pequenas cenas
coordenam animações e a vocalização no momento da comemoração, carinho ou saudação.

Por padrão, a configuração JSON, backup, lock e logs ficam no caminho retornado
por `QStandardPaths.AppLocalDataLocation`, normalmente
`%LOCALAPPDATA%\R2DesktopCompanion\R2Companion`. Preferências e posição são gravadas
com substituição atômica e debounce; não são gravadas a cada frame. Arquivos
corrompidos têm recuperação por backup; schema futuro é preservado sem sobrescrita.
Uma segunda instância com o mesmo diretório é rejeitada.
Tarefas e notas ficam em `tools.json`, com backup e recuperação separados da
configuração. Os limites são 500 tarefas, 100 notas, 50.000 caracteres por nota e
8 MiB no documento completo. Um erro de gravação permanece visível nas ferramentas.
Atualizações do executável não substituem esses arquivos.

Iniciar com o Windows começa desmarcado. Por segurança, fica indisponível durante
execução pelo Python e em builds ainda dentro de `dist`, `build`, `temp` ou `tmp`.
Depois de copiar **a pasta completa** do executável para um local estável, habilite
explicitamente em Configurações. Somente o valor `R2Companion` de
`HKCU\Software\Microsoft\Windows\CurrentVersion\Run` é gerenciado, com verificação
de propriedade. Não cria scripts, serviços ou tarefas agendadas. Não foi registrado
nenhum item de inicialização durante esta implementação.

Antes de mover/apagar a instalação, desmarque essa preferência. O Windows pode
desabilitar a entrada em Aplicativos de inicialização; o Companion não força sua
reativação. A ordem em relação aos sons físicos é independente e não garantida.

## Testar

```powershell
.\.venv\Scripts\python.exe -m pip install --no-cache-dir -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q --basetemp .runtime-tests
.\.venv\Scripts\python.exe run_companion.py --data-dir .runtime-smoke --smoke-test
```

Para reproduzir também as versões transitivas do ambiente usado nesta entrega,
instale `requirements-lock.txt` em um ambiente virtual novo.

Os testes incluem lógica, persistência, geometria simulada de vários monitores,
animações, UI Qt e um teste nativo Windows com uma janela temporária de outro
processo. Esse teste verifica hit testing e foco sem enviar cliques a aplicações
do usuário. Os testes gráficos precisam de uma sessão Windows interativa.

`tools/preview_garage.py` exporta poses em 160 px e sequências animadas para
`local_docs/v12-visual/animations.html`. `tools/generate_garage.py` reproduz
somente os quatro novos modelos; não regrava os atlas anteriores.

O estresse da roda registra cada sequência e preserva as falhas em uma pasta nova:

```powershell
.\.venv\Scripts\python.exe tools\stress_radial.py --data-dir .runtime-wheel-stress --cycles 140
```

Medição curta opcional (gera relatório local e encerra):

```powershell
.\.venv\Scripts\python.exe tools\profile_companion.py --seconds 60 --data-dir .runtime-profile
```

O perfil divide o tempo entre repouso, animação/caminhada e janela oculta. Ele
desativa detecção de tela cheia e sono por inatividade para controlar a carga de
teste; não altera os dados normais do usuário. Não substitui um teste prolongado.

Para observar o primeiro passeio automático com o agendador real e verificar o
balão durante o movimento (dados isolados, sessão mantida acordada para o ensaio):

```powershell
.\.venv\Scripts\python.exe tools\verify_autonomy.py
```

O roteiro `tools/verify_v11.py` captura as telas, testa vocalização a 5% de volume
e usa uma release fictícia apenas para validar a interface. O roteiro
`tools/verify_update_center.py` exercita download, cópia independente da central,
encerramento, backup e reinício com executáveis e transporte local de teste.
Os relatórios ficam em pastas `.runtime-*`, sem alterar os dados normais.

O ensaio `tools/verify_post_update.py --data-dir .runtime-upgrade-121` usa o build
real anterior em `dist/1.1.1/R2Companion` e o ZIP atual. Abre ferramentas e Garage,
atualiza em cópia isolada, testa a roda no primeiro reinício e compara com abertura
direta. `--legacy-updater` exercita o instalador anterior; `--fail-startup` injeta
uma falha local para verificar a recuperação. Esses ensaios gráficos devem rodar
separadamente, depois da suíte Qt, para evitar disputa de foco entre testes.

Para conferir os painéis novos e a reprodução Qt com dados isolados, execute
`tools\verify_features.py` pelo mesmo Python do ambiente virtual. Esse ensaio
reproduz um efeito a 5% de volume e salva capturas/diagnóstico em `.runtime-features-v03`.
Depois do build, `tools\verify_package.py` verifica ZIP/hash e abre o EXE com PATH
restrito ao Windows. `tools\verify_release.py` ensaia a migração real 1.1.1 → versão atual
em cópias locais; requer também o build anterior preservado em dist/1.1.1.

## Gerar o executável

```powershell
.\.venv\Scripts\python.exe tools\build_windows.py
.\dist\1.2.0\R2Companion\R2Companion.exe
```

O build é Windows x64, one-folder, sem console e sem solicitação de elevação.
O script mantém o cache do empacotador no projeto. Distribua **toda a pasta**
`dist\1.2.0\R2Companion`, incluindo `_internal`, assets, `release.json` e licenças.
O ZIP e SHA-256 são gerados em `dist\R2Companion-Windows-x64.zip` e `.zip.sha256`.
Para validar uma candidata preservando esses artefatos, use
`tools\build_windows.py --artifact-label garage-120-rc1`; o rótulo separa
a pasta, o ZIP e o checksum. `verify_package.py --artifact-label` e os ensaios
de atualização com `--archive` aceitam esses pacotes locais sem publicá-los.
Ao testar a candidata com verify_post_update.py, use também
`--require-navigation-trace`: o verificador aguarda a conclusão registrada do
smoke antes de iniciar seu próprio fluxo de cliques, inclusive com o instalador
legado sem confirmação de inicialização.
Não copie somente o EXE. O spec inclui Qt Multimedia, seus plugins e dependências;
exclui QML/Quick/Test e outros módulos não utilizados.
O executável não tem assinatura digital nesta entrega. Antes de publicação,
o proprietário deve definir a licença do projeto/arte e revisar as obrigações
das bibliotecas incluídas em [THIRD_PARTY_NOTICES.md](packaging/docs/THIRD_PARTY_NOTICES.md).

Diagnóstico do executável, sem usar o diretório normal de dados:

```powershell
.\dist\1.2.0\R2Companion\R2Companion.exe --data-dir .runtime-exe --smoke-test
```

Se não abrir, consulte `companion.log` no diretório escolhido. Configuração inválida
usa backup/default; erro de leitura do manifesto/PNG obrigatório impede início e
gera mensagem/log. Caminho favorito indisponível mostra erro sem chamar um shell.

A navegação também registra `navigation.jsonl` no diretório de dados, com PID,
identificador da interação, página, animação, gate, callback e estado da ferramenta.
O arquivo possui rotação de 1 MiB e até três backups. Para incluir os eventos Qt
de entrada e foco, defina `$env:R2_NAV_TRACE = '1'` antes de iniciar. Remova essa
variável ou use `0` para manter somente os registros essenciais. A gravação ocorre
fora da thread da interface; o log não inclui textos de tarefas, notas ou favoritos.

Para atualizar do pacote anterior, encerre a versão antiga pelo menu Sair e extraia
o novo ZIP em outra pasta. As preferências/favoritos no diretório normal são reutilizados.
O build usa pastas por versão para preservar executáveis anteriores durante desenvolvimento.

## Automatic Updates

O usuário final precisa de **Windows 10/11 x64**, Windows PowerShell 5.1 e internet
para consultar e baixar atualizações. Python, PyInstaller e Git não são necessários.
Extraia o ZIP completo em uma pasta do usuário com permissão de gravação, como
`%LOCALAPPDATA%\Programs\R2Companion`, e execute `R2Companion.exe`.

No menu, escolha **Verificar atualizações**. Uma central Qt com o tema do personagem equipado mostra
consulta, versão atual, novidades da release, download, integridade e instalação.
A consulta e o download rodam em worker separado. A barra usa bytes recebidos e
o tamanho publicado; fases sem porcentagem conhecida usam indicador indeterminado.
A consulta não fecha o mascote. Ao iniciar uma operação, o botão é desabilitado imediatamente. A central permanece visível e impede fechamento ou Escape durante o processamento; ao concluir ou falhar, pode ser fechada.
Se houver versão mais nova, confirme o download e a instalação. O atualizador
consulta a última release estável do repositório registrado em `release.json`,
verifica SHA-256, extrai em staging validado e somente então encerra o R2 de forma
graciosa. Cria um backup completo ao lado da instalação, substitui os arquivos e
reinicia o aplicativo. A partir do instalador 1.1.2, o novo processo confirma PID,
versão carregada, bundle e diretório de dados depois de inicializar os serviços e
conectar a interface. Sem confirmação em 30 segundos, o instalador solicita a
recuperação do backup. Sem atualização ou ao cancelar, o processo atual continua.
Não há verificação nem download automático na inicialização.

Para executar manualmente, use o script incluído no pacote:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\Programs\R2Companion\_internal\scripts\update-r2-companion.ps1"
```

`-CheckOnly` apenas consulta; `-Console` apresenta o resultado no terminal;
`-Yes` autoriza explicitamente a instalação sem a pergunta; `-NoRestart` impede
reinício. `-InstallDirectory` informa uma instalação diferente e `-DataDirectory`
preserva um diretório personalizado de dados fora da instalação. O Bypass vale
somente para esse processo e não altera a política persistente do Windows.

Logs: `%LOCALAPPDATA%\R2DesktopCompanion\R2Companion\updates\update.log`, ou a pasta
`updates` do diretório de dados selecionado. O processo iniciado pelo menu fica
sem console e informa o resultado por uma janela pequena.

| Situação | Ação |
| --- | --- |
| Sem release estável, HTTP 404, rede indisponível ou limite da API | Verifique conexão e publicação da release; tente depois. A instalação permanece intacta. |
| SHA-256 errado, ZIP inválido ou incompleto | A instalação é cancelada antes de substituir arquivos. Baixe novamente da release configurada. |
| Sem permissão ou instalação em Program Files | Instale em uma pasta do seu usuário com permissão de gravação. Não é necessário administrador. |
| R2 não encerra em 15 segundos | Feche pelo menu Sair e tente novamente. O atualizador não força encerramento de processos. |
| Dados personalizados dentro da instalação | Mova-os para uma pasta do perfil e use `--data-dir`; o atualizador recusa substituir essa instalação com dados internos. |
| Falha na substituição ou no início da versão nova | O atualizador tenta restaurar o backup e reiniciar a versão anterior; consulte o log. |

O backup fica em `<instalação>.backup-<identificador>`. Se uma interrupção externa
impedir a recuperação automática, encerre o R2, preserve a pasta que falhou e mova
o backup para o caminho original da instalação. Tarefas, notas e preferências
continuam no perfil do usuário. Backups e possíveis pastas `.failed-*` são mantidos
para diagnóstico; podem ser removidos manualmente depois da validação.

Durante a instalação, a central cria uma cópia temporária do bundle em
`updates/center-*`, fora da pasta substituída, para continuar visível enquanto o
R2 reinicia. A central original só fecha após a sucessora confirmar que está visível; a instalação aguarda a confirmação dessa transferência. Downloads e logs ficam em `updates/download-*`. Essas pastas podem
ser removidas com a central fechada. O instalador reconsulta a release e verifica
novamente o checksum publicado, além da validação feita no download pela interface.

A versão 0.2.0 não incluía metadata nem atualizador. Para migrar dela, instale
manualmente a pasta 1.2.0 completa uma vez; os dados normais serão reutilizados.
Mantenha `release.json` e o diretório `_internal` junto ao executável.

Para iniciar com o Windows, copie a instalação para um local estável e marque
**Iniciar com o Windows** nas Configurações. Para desativar, desmarque antes de
mover/remover o aplicativo. É gerenciada apenas a entrada própria no registro HKCU
Run; **não existe tarefa agendada a remover**. Uma atualização no mesmo caminho
preserva essa entrada. Os scripts externos do casemod permanecem independentes.

Para publicar uma versão, o desenvolvedor deve:

1. Atualizar a versão em `pyproject.toml`, `src/r2_companion/__init__.py` e `packaging/windows.manifest`, executar os testes e registrar as alterações.
2. Criar a tag `vX.Y.Z`, correspondente à versão do projeto.
3. Enviar a tag ao GitHub, por ação explícita do desenvolvedor.
4. Acompanhar o workflow Windows release: dependências, testes, build e smoke do executável.
5. Conferir a GitHub Release e seus arquivos `R2Companion-Windows-x64.zip` e `R2Companion-Windows-x64.zip.sha256`.
6. Baixar, conferir o hash e testar o pacote e a atualização em um perfil descartável.

O workflow grava o repositório real de `github.repository` na metadata. Em builds
locais, o builder usa `origin`, ou o único remoto disponível. Use
`--repository owner/repo` se houver ambiguidade. `workflow_dispatch` permite testar
o build sem publicar release; a publicação depende de tag `v*`. A integração usa a
API pública sem credenciais e pressupõe releases e assets acessíveis publicamente.
O checksum detecta corrupção; o pacote ainda não tem assinatura digital.

O instalador já distribuído na versão 1.1.1 usa seu protocolo anterior de migração.
O executável atual verifica a correspondência entre código e bundle
também nessa primeira migração; as atualizações iniciadas a partir da 1.1.2 usam
a confirmação completa do reinício.

A arquitetura separa pet (estados, animação e movimento), services (áudio,
Windows, persistência e updates), features (ferramentas) e ui (menus e painéis).
A documentação interna e evidências ficam em `local_docs/`, ignorado pelo Git. Changelog, notas de versão e avisos de terceiros públicos ficam em `packaging/docs/`.

Continuam pendentes validações físicas em Windows 11, monitores com DPI misto,
suspensão real e teste prolongado. Os modelos anteriores mantêm seus recursos gráficos originais.

As notas públicas descrevem funcionalidades, correções e instruções de uso. Resultados de testes, investigações e evidências permanecem na documentação interna.
