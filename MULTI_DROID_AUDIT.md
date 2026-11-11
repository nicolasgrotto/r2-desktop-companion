# Auditoria da evolução multi-droides

Base: `5fc189a`, 10/11/2026 11:25:00 −03:00. Versão mantida: 1.1.0.

O status inicial continha somente `ARCHITECTURE.md` não rastreado. Esse documento
local permanece intacto. Nenhuma operação de descarte é necessária.

Já existem AudioService/Qt Multimedia, 15 efeitos, 12 sílabas, 30 frases,
ReactionDirector, Calm/Curious/Communicative, carinho, quatro cores, hologramas,
diagnóstico, horário de silêncio, minigames/Duel of Fates, ferramentas, tarefas,
notas e central de atualização em processo separado. A evolução reutiliza esses
componentes. PetController continua sendo a única autoridade de estados.

Positioner concentra geometria, múltiplos monitores, arrasto, cantos e limites;
AnimationManager usa QTimer single-shot e atlas PNG. O atlas padrão tem canvas
64 × 64, âncora (32,56), transparência, quatro colunas e vinte estados. O manifesto
e o README classificam a arte padrão como provisória; ela não será substituída.

ConfigStore usa schema 1 aditivo, QSaveFile, backup, recuperação de corrupção,
debounce e lock. Produtividade possui arquivo próprio. O diretório de dados e a
versão de schema serão preservados. Os campos legados continuarão representando
as preferências do personagem equipado para compatibilidade das interfaces.

Não existem perfis de droides, garagem, galeria ou central dedicada de áudio.
Estilos estão parcialmente centralizados em ui/theme.py, com estilos e pinturas
locais em bubble/radial/productivity/tools/targets/updates. Todos precisam receber
tokens de tema. A central de atualização precisa ler o tema do arquivo, pois roda
fora do processo principal.

O spec PyInstaller inclui recursivamente assets. O construtor atual sobrescreve
dist/1.1.0; a validação desta evolução usará diretórios separados para preservar
artefatos anteriores. A suíte existente é executada antes e depois das mudanças.
