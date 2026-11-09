# R2 Desktop Companion

Mascote desktop local para Windows 10/11, em Python/PySide6. Robô branco e azul com
janela transparente, animações por atlas/PNG e comportamento convencional.
**Não utiliza IA, rede, APIs web, backend, modelos locais ou telemetria.**

Esta versão funcional usa **arte provisória original**, não os sprites HD finais.
O Companion é independente do casemod e não executa nem altera seus scripts de som.

**Versão 0.2.0:** balões acompanham o robô, passeios autônomos têm prazo definido,
clique esquerdo abre uma roda de ações e os painéis ganharam identidade azul/branca,
busca de favoritos e temporizador circular. Não houve alteração no formato dos dados.

## Executar pelo código

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

- Clique esquerdo: reação, fala e roda de ações essenciais. Use o centro R2 ou Esc para fechar a roda; clicar fora também fecha. Arraste com o botão esquerdo para reposicionar — o balão acompanha o personagem.
- Botão direito: Interagir, Aplicativos, Atalhos, Ferramentas, Configurações e Sair.
- Ferramentas: relógio/data em destaque, temporizador com minutos/segundos e atalhos de 1/5/25 minutos, CPU/RAM e bateria quando disponível.
- Na roda, Aplicativos e Meus locais abrem painéis com busca e seleção. Use Gerenciar favoritos para editar destinos. Explorar faz o R2 dar um passeio imediatamente, quando houver espaço.
- Configurações: tamanho, frequência, caminhada, inatividade, som, balões, prioridade da janela, aplicativos e locais favoritos.
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
indefinidamente. Caminhadas permanecem curtas e dentro do monitor atual.

O temporizador pode pausar, continuar e reiniciar. Continua com o robô dormindo,
oculto ou com autonomia pausada. O tempo de suspensão do computador conta;
conclusões vencidas são processadas uma vez após retomar. Sair da aplicação
encerra a contagem: restaurar temporizadores entre execuções não é suportado.
Uma conclusão permanece indicada em Ferramentas, mesmo se o Windows ocultar o aviso.

## Dados e inicialização automática

Por padrão, a configuração JSON, backup, lock e logs ficam no caminho retornado
por `QStandardPaths.AppLocalDataLocation`, normalmente
`%LOCALAPPDATA%\R2DesktopCompanion\R2Companion`. Preferências e posição são gravadas
com substituição atômica e debounce; não são gravadas a cada frame. Arquivos
corrompidos têm recuperação por backup; schema futuro é preservado sem sobrescrita.
Uma segunda instância com o mesmo diretório é rejeitada.

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

## Gerar o executável

```powershell
.\.venv\Scripts\python.exe tools\build_windows.py
.\dist\0.2.0\R2Companion\R2Companion.exe
```

O build é Windows x64, one-folder, sem console e sem solicitação de elevação.
O script mantém o cache do empacotador no projeto. Distribua **toda a pasta**
`dist\0.2.0\R2Companion`, incluindo `_internal`, assets e licenças. Não copie somente
o EXE. O spec exclui Qt Network/QML/Quick/Test e outros módulos não utilizados.
O executável não tem assinatura digital nesta entrega. Antes de publicação,
o proprietário deve definir a licença do projeto/arte e revisar as obrigações
das bibliotecas incluídas em [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Diagnóstico do executável, sem usar o diretório normal de dados:

```powershell
.\dist\0.2.0\R2Companion\R2Companion.exe --data-dir .runtime-exe --smoke-test
```

Se não abrir, consulte `companion.log` no diretório escolhido. Configuração inválida
usa backup/default; erro de leitura do manifesto/PNG obrigatório impede início e
gera mensagem/log. Caminho favorito indisponível mostra erro sem chamar um shell.

Para atualizar do pacote anterior, encerre a versão antiga pelo menu Sair e extraia
o novo ZIP em outra pasta. As preferências/favoritos no diretório normal são reutilizados.
O build usa pastas por versão para preservar executáveis anteriores durante desenvolvimento.

## Arquitetura e extensão

- [Proposta de referência](docs/companion/ARCHITECTURE_PROPOSAL.md).
- [Arquitetura implementada e decisões](docs/companion/ARCHITECTURE.md).
- [Adicionar sprites e comportamentos](docs/companion/ASSET_GUIDE.md).
- [Evidências e validações Windows pendentes](docs/companion/WINDOWS_VALIDATION.md).
- [Inventário da entrega](docs/companion/DELIVERY.md).

Continuam necessários sprites HD definitivos, validação em Windows 11 e múltiplos
monitores físicos/DPI misto, suspensão real, teste prolongado e revisão visual pelo
usuário. A lógica desses recursos não deve ser confundida com validação em hardware.
