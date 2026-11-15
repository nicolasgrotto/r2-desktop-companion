# Prova isolada de sessões de mídia do Windows

`media_probe.py` investiga o acesso GSMTC pelo Python. Não é importado pelo
Companion e não adiciona música à aplicação. Usa os bindings modulares
[PyWinRT](https://pywinrt.readthedocs.io/en/latest/installing/), fixados em
`requirements-media-probe.txt`; mantenha-os em um ambiente separado.

A API enumera aplicativos que publicam controles de mídia no Windows e está
disponível desde Windows 10 1809. Compatibilidade depende do fornecedor da
sessão. Consulte o [contrato do gerenciador da Microsoft](https://learn.microsoft.com/en-us/uwp/api/windows.media.control.globalsystemmediatransportcontrolssessionmanager).

## Preparação

Na raiz do repositório, com Python x64:

```powershell
$probeRoot = Join-Path $PWD ('.runtime-v13-media-' + [guid]::NewGuid().ToString('N'))
python -m venv "$probeRoot/venv"
& "$probeRoot/venv/Scripts/python.exe" -m pip install -r tools/requirements-media-probe.txt
& "$probeRoot/venv/Scripts/python.exe" tools/media_probe.py snapshot --data-dir "$probeRoot/snapshot"
& "$probeRoot/venv/Scripts/python.exe" tools/media_probe.py watch --seconds 30 --data-dir "$probeRoot/watch"
```

`snapshot` é a ação padrão. `watch` observa eventos de sessões, sessão corrente,
metadados e reprodução; os callbacks são encaminhados à thread do asyncio,
conforme o [modelo de threads do PyWinRT](https://pywinrt.readthedocs.io/en/latest/threads/).
Uma leitura ocorre por vez, agrupando notificações recebidas durante a leitura.

Não há reprodução automática ao iniciar ou pausa ao sair. O probe lê os
metadados, mas registra apenas sua presença. Títulos, artistas e mensagens
arbitrárias de exceções do fornecedor não entram no JSON. IDs de aplicativos,
versões, capacidades, estado e códigos HRESULT aparecem na saída.

## Comandos explícitos

Copie o valor `source` da sessão desejada. Cada comando exige `--source` e é
enviado uma única vez ao objeto selecionado; ausência, duplicidade ou capacidade
desabilitada impedem o envio. Não há troca automática para outro player.

```powershell
& "$probeRoot/venv/Scripts/python.exe" tools/media_probe.py play --source 'ID_EXATO_DO_PLAYER'
& "$probeRoot/venv/Scripts/python.exe" tools/media_probe.py pause --source 'ID_EXATO_DO_PLAYER'
& "$probeRoot/venv/Scripts/python.exe" tools/media_probe.py previous --source 'ID_EXATO_DO_PLAYER'
& "$probeRoot/venv/Scripts/python.exe" tools/media_probe.py next --source 'ID_EXATO_DO_PLAYER'
& "$probeRoot/venv/Scripts/python.exe" tools/media_probe.py cancel --data-dir "$probeRoot/cancel"
```

`accepted` significa que o método remoto retornou verdadeiro; confirme também
o estado/evento e o comportamento do player. As operações são definidas pelo
[contrato de sessão da Microsoft](https://learn.microsoft.com/en-us/uwp/api/windows.media.control.globalsystemmediatransportcontrolssession).

`cancel` solicita cancelamento nativo de `request_async()`. A conclusão pode
ganhar a corrida: `completed_before_cancel` não prova uma operação cancelada.

## Evidências e falhas

- JSON Lines é impresso no terminal. `--data-dir` grava também `events.jsonl`
  em um diretório novo; um diretório existente é recusado.
- `--timeout` vale por chamada assíncrona (padrão 5 segundos), mais até 0,5 s
  para cancelamento. O relógio de observação usa tempo monotônico.
- Código 0: execução bem-sucedida, inclusive zero sessões. Código 1: falha de
  acesso, dependência, leitura, timeout ou limpeza. Código 2: comando recusado,
  não suportado, alvo ausente/ambíguo, ou argumentos inválidos. Ctrl+C: 130.
- `0x80070005` indica acesso negado. Verifique o contexto da sessão Windows e
  as restrições do executor antes de concluir incompatibilidade da API.
- As assinaturas são removidas ao terminar; falha na remoção é registrada e
  torna a execução malsucedida. Callbacks tardios não iniciam novas leituras.

Testes locais da política de comandos, privacidade e cancelamento:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_media_probe.py
```

Esses testes usam doubles e não certificam players reais. Registre separadamente
ausência de player, comandos, troca/encerramento de sessões, eventos e
cancelamento em uma sessão nativa. Resultados e matriz de aplicativos ficam em
`local_docs/`. O roteiro abaixo prepara a prova no executável portátil.

## Executável portátil de investigação

Use outro ambiente, com apenas as dependências mínimas e a ferramenta de build.
O hook do [PyWinRT para PyInstaller](https://pywinrt.readthedocs.io/en/latest/freezing/)
coleta os namespaces instalados e suas tabelas `_table.pywinrt`; por isso, não
use o ambiente que contém os módulos adicionais dos players de teste.

```powershell
$packageRoot = Join-Path $PWD ('.runtime-v13-media-package-' + [guid]::NewGuid().ToString('N'))
python -m venv "$packageRoot/build-env"
& "$packageRoot/build-env/Scripts/python.exe" -m pip install -r tools/requirements-media-probe-build.txt
& "$packageRoot/build-env/Scripts/python.exe" tools/build_media_probe.py --output-dir "$packageRoot/artifact"
python tools/verify_media_probe_package.py --archive "$packageRoot/artifact/R2MediaProbe-Windows-x64.zip" --data-dir "$packageRoot/verification"
```

O build recusa versões divergentes e namespaces WinRT extras. Produz um ZIP
onedir, checksum SHA-256, licenças, log e inventário dos arquivos. Cada saída
precisa de um diretório novo; o `dist/` estável do Companion não é utilizado.

Depois de extrair o ZIP, mantenha a pasta `_internal` ao lado do executável:

```powershell
.\R2MediaProbe.exe snapshot --data-dir '.\evidence-snapshot'
.\R2MediaProbe.exe watch --seconds 30 --data-dir '.\evidence-watch'
```

Os comandos explícitos usam a mesma sintaxe `--source` da versão Python. O
EXE não instala nem registra um aplicativo no Windows. O evento `environment`
registra `frozen`, versões, elevação do token e presença de identidade de pacote,
permitindo verificar as condições de cada ensaio.

O verificador extrai em outro caminho, restringe PATH a System32 e remove
variáveis Python/Qt do processo filho. Verifica enumeração, observação,
cancelamento e um prazo mínimo para provocar timeout nativo. Se a operação
concluir antes do prazo nas três tentativas, o timeout permanece não validado;
isso não demonstra falha do produto. Nenhum comando de reprodução é enviado
por esse verificador. A prova de comandos/eventos exige uma sessão controlada
e resultados separados. Não declare compatibilidade com players ou versões
do Windows que não tenham sido exercitados.
