# Componentes de terceiros

Este é um build de desenvolvimento offline. Os assets provisórios originais
estão descritos em `src/r2_companion/assets/LICENSES.md`.

| Componente | Versão testada | Referência de licença/proveniência |
| --- | --- | --- |
| CPython | 3.13.12 | Python Software Foundation e licenças incorporadas; LICENSE.txt do runtime |
| PySide6-Essentials / Qt | 6.10.2 | Licenças Qt/PySide6 e seus componentes nos arquivos da distribuição |
| Shiboken6 | 6.10.2 | Licenças da distribuição Shiboken |
| psutil | 7.2.2 | BSD-3-Clause, licença da distribuição psutil |
| PyInstaller | 6.19.0 | GPL com exceção de distribuição do bootloader; licença do empacotador |

O spec de empacotamento copia os textos de licença presentes nas distribuições
instaladas para `licenses/` dentro do pacote. Preserve esse diretório e este
documento ao copiar a pasta do aplicativo. As bibliotecas Qt ficam dinâmicas no
bundle one-folder. A revisão das obrigações de redistribuição, a licença do
código do projeto e a licença dos futuros sprites devem preceder uma publicação
pública; este inventário não substitui os termos completos incluídos.

Referências oficiais:

- [Qt for Python: licenças](https://doc.qt.io/qtforpython-6/licenses.html)
- [Python: licença](https://docs.python.org/3/license.html)
- [psutil: repositório](https://github.com/giampaolo/psutil)
- [PyInstaller: licença](https://pyinstaller.org/en/stable/license.html)
