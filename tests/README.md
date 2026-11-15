# Executar os testes

Use Python 3.12 ou 3.13 x64 no Windows e as dependências de
`requirements-lock.txt`. Execute a partir da raiz do repositório. Os grupos
reduzidos dispensam desktop interativo, mas continuam usando dependências e
semântica de caminhos do Windows; não constituem uma suíte Linux certificada.

## Grupos e seleção

Cada teste recebe exatamente uma marca antes de o pytest aplicar `-m`:

| Marca | Dependências e cobertura |
|---|---|
| `logic` | Regras, configuração, geometria, parsing e doubles, sem criar uma aplicação Qt ou chamar integração Windows real. Pode importar Qt e usar tipos de valor como `QRectF`. |
| `qt` | Fixture `qapp`, direta ou indireta; sinais, timers, persistência Qt, widgets e renderização compatíveis com `offscreen`. Não valida foco, empilhamento ou hit testing nativos. |
| `windows_native` | Fixture `native_desktop`, direta ou indireta, ou marca explícita; Companion completo, janelas/foco, APIs Windows reais e integração PowerShell. Requer desktop Windows acessível e plataforma Qt `windows`. |

`tests/conftest.py` considera a cadeia de fixtures, inclusive `autouse` e fixtures
importadas. `pet` e `companion` exigem `native_desktop`; isso inclui seus
consumidores em outros arquivos. A fixture `center` cobre apresentação real da
central de atualização. Testes que criam `Companion` diretamente, chamam o
instalador PowerShell ou consultam unidades Windows têm marca explícita.

A fixture `companion` dos testes de interação interrompe a saudação agendada
e começa em `IDLE`, para que a latência da criação das janelas não altere a
precondição de uma ação explícita. As assertions de caminhada e interação
continuam verificando o controlador e as janelas reais.

Sem uma marca explícita, a prioridade é `native_desktop` → `qapp` → `logic`.
Marcas conflitantes ou que subestimam essas fixtures são erro de coleta.
Isso não analisa o corpo Python: ao acrescentar acesso nativo direto, marque
`@pytest.mark.windows_native`; ao criar fixtures nativas, faça-as depender de
`native_desktop`. Para uma fixture que cria QApplication, use `qapp`, inclusive
quando precisar apenas renderizar imagens. Não esconda essas dependências em
`request.getfixturevalue()` ou na criação manual de QApplication.

Um nome contendo `windows` não basta: testes de `preserve_window_stack`,
detecção de tela cheia e apresentação que substituem as APIs por doubles são
lógica. Um teste aparentemente puro em módulo com fixture nativa `autouse`
continua sendo nativo. Sempre confira a seleção com `--collect-only` e
`--test-inventory` quando mudar fixtures compartilhadas.

## Comandos locais

Crie uma raiz nova a cada execução. `--basetemp` é apagado pelo pytest quando
reutilizado, portanto não aponte para dados reais ou evidências anteriores.

```powershell
$testRoot = Join-Path $PWD ('.runtime-tests-' + [guid]::NewGuid().ToString('N'))
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -m pytest -q -m logic --basetemp "$testRoot/logic" --junitxml "$testRoot/logic.xml" --test-inventory "$testRoot/logic.json"
.\.venv\Scripts\python.exe -m pytest -q -m qt --basetemp "$testRoot/qt" --junitxml "$testRoot/qt.xml" --test-inventory "$testRoot/qt.json"
```

Para conferir somente a lista, sem executar fixtures ou abrir janelas:

```powershell
.\.venv\Scripts\python.exe -m pytest --collect-only -q -m windows_native --test-inventory "$testRoot/native-selection.json"
```

Em uma sessão Windows interativa, desbloqueada, fora de executores que negam
acesso ao desktop:

```powershell
$env:QT_QPA_PLATFORM = 'windows'
.\.venv\Scripts\python.exe -m pytest -q -m windows_native --basetemp "$testRoot/native" --junitxml "$testRoot/native.xml" --test-inventory "$testRoot/native.json"
# Gate integral, em vez de repetir os grupos quando não houver motivo:
.\.venv\Scripts\python.exe -m pytest -q --basetemp "$testRoot/full" --junitxml "$testRoot/full.xml" --test-inventory "$testRoot/full.json"
```

A seleção nativa com `offscreen` ou em outro sistema termina com erro de uso.
Desktop inacessível/bloqueado gera erro de preparação, não skip nem aprovação.
A verificação inicial não substitui as assertions reais de foco, transparência
e ordem das janelas. Exceções em callbacks continuam capturadas por
`slot_errors`, inclusive na drenagem de objetos Qt ao final do teste.

Para reduzir por subsistema, combine arquivos e marcas:

| Subsistema | Arquivos principais / seleção |
|---|---|
| Configuração e persistência | `test_config_storage.py`, `test_audio_productivity.py`, `test_companion_state.py` com `-m 'logic or qt'`; `test_companion_state_native.py` para troca de droide, reinício e avisos no desktop |
| Timer e comportamento | `test_timer_behavior.py`, `test_timer_stop_v121.py`, `test_context_v03.py`; use a marca para distinguir serviço de integração |
| Personagens e recursos | `test_droids.py`, `test_garage_expansion.py`, `test_animation_refinement.py`; modelos/renderização em Qt, equipamento/Companion em nativo |
| Temas e tarefas assíncronas | `test_theme_events.py`, `test_task_lifecycle.py` com `-m qt` |
| Navegação e camadas | `test_navigation_v111.py`, `test_radial_reliability.py`, `test_window_layers.py`, `test_windows_native.py` com `-m windows_native` |
| Atualização | `test_update*.py`, `test_post_update_integrity.py`; cliente/doubles em lógica, widgets em Qt, PowerShell/apresentação em nativo |
| Probe musical | `test_media_probe.py` com `-m logic`; prova WinRT/EXE separada em `tools/media_probe.md` |
| Infraestrutura da seleção | `test_test_groups.py` com `-m qt`; executa pytest em subprocessos descartáveis e verifica falhas deliberadas |

Exemplo: `python -m pytest -q tests/test_timer_behavior.py tests/test_timer_stop_v121.py -m 'logic or qt'`.
Nenhum desses subconjuntos substitui a regressão integral na candidata.

## CI e pacote

- `checks.yml`: pull requests e execução manual, Windows x64/Python 3.12 e 3.13,
  jobs separados de lógica e Qt com `offscreen`; conserva JUnit e inventário.
- `native-validation.yml`: execução manual, Python 3.13, testes nativos seguidos
  de build com rótulo exclusivo e smoke do EXE com PATH restrito. Se o runner
  hospedado não fornecer um desktop utilizável, o job falha: repetir a rota
  local e registrar a ausência de validação remota. Não há fallback `offscreen`.
- `release.yml`: fluxo de publicação existente, separado desses checks. A
  adição dos workflows não configura branch protection nem publica releases.

Os jobs novos têm permissão de leitura e não recebem segredos de publicação.
O fluxo manual precisa existir na branch padrão para aparecer na interface do
GitHub; somente criar o arquivo local não executa CI remoto.

Smoke local de pacote com artefato separado:

```powershell
$artifactLabel = 'check-' + [guid]::NewGuid().ToString('N')
$env:QT_QPA_PLATFORM = 'windows'
.\.venv\Scripts\python.exe tools/build_windows.py --artifact-label $artifactLabel
.\.venv\Scripts\python.exe tools/verify_package.py --artifact-label $artifactLabel --data-dir "$testRoot/package"
```

O verificador usa 20 segundos de smoke por padrão (`--smoke-seconds` aceita
5–120), mais 45 segundos de margem para o processo iniciar e encerrar. O prazo
não substitui as assertions: todos os sete personagens e a navegação precisam
concluir. O verificador cobre ZIP/hash/recursos, inicialização, sete personagens,
navegação e encerramento com PATH restrito. Use sessão nativa; um smoke não
certifica sozinho a experiência interativa nem o ensaio prolongado.

Referências: [seleção e hooks do pytest](https://docs.pytest.org/en/stable/how-to/writing_hook_functions.html),
[eventos dos workflows GitHub](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows).
