# Assets de desenvolvimento

`characters/default/placeholder.png`, `icons/companion.png`, `icons/companion.ico`
e `sounds/completion.wav` são placeholders originais criados para este projeto
pelo gerador local `tools/make_placeholders.py`, em 2026-11-09.
Não contêm sprites, sons, logotipos ou material extraído de franquias.
O PNG é um desenho geométrico de desenvolvimento, não a arte HD final.

O manifesto identifica o personagem como `original-development-placeholder`.
O gerador não é executado pelo aplicativo. A licença de distribuição do projeto
e dos futuros assets definitivos deve ser estabelecida pelo proprietário antes
de publicação pública. Não há autorização implícita para reutilizar assets de
outros repositórios. Registre autor, licença, origem e alterações de substituições aqui.

## Assets 0.3.0

Em 11/11/2026 o gerador local `tools/generate_sounds.py` produziu 15 efeitos
originais por síntese matemática de ondas senoidais, envelopes e ruído determinístico.
Não há samples, vozes, gravações ou material de terceiros. Arquivos PCM mono de
22.050 Hz/16 bits, entre 0,24 e 0,54 segundo, nas categorias idle, movement,
reactions, sleep e notifications. `sounds/completion.wav` anterior foi preservado.

O atlas original foi ampliado por `tools/make_placeholders.py` para as novas
expressões, sem recursos externos. O desenho continua sendo a pixel art original
provisória branca, azul e cinza do projeto. A proveniência é local; a escolha da
licença de distribuição do projeto e desses assets continua a cargo do proprietário.

## Voz e ícones 1.1.0

`voice/*.wav` contém 12 sílabas originais geradas por `tools/generate_voice.py`.
São sínteses PCM mono 22.050 Hz/16 bits com glissandos, trilos, modulação, envelopes
e ruído determinístico. Não utilizam gravações, samples ou áudios de filmes.
`services/vocalizations.py` combina as sílabas em 30 frases curtas para dez emoções,
em cache temporário por execução. Os 15 efeitos anteriores foram preservados.

O símbolo de duelo em `ui/theme.py` é um desenho vetorial original do projeto.
Nenhuma imagem, trilha ou recurso do Duel of Fates foi copiado ou empacotado;
o catálogo abre somente a URL informada no navegador padrão. As variações de cor
reutilizam o atlas original, preservando forma, transparência e animações.

## Multi-droides — evolução local 1.1.0

Em 12/11/2026, `tools/generate_droids.py` produziu os recursos de Vesper e Orbita
em `droids/dark_astromech` e `droids/spherical_droid`. São desenhos originais em
pixel art procedural, sem insígnias, logotipos ou arquivos extraídos de franquias.
O padrão referencia o atlas anterior, preservado. Os novos desenhos têm aprovação
artística final pendente, registrada também nos perfis e interfaces.

Cada novo personagem possui 12 sílabas PCM originais (mono, 22050 Hz, 16 bits),
geradas por síntese matemática, sem samples. As frases usam o compositor existente
com mapeamentos próprios; efeitos comuns continuam sendo os originais do projeto.
A definição de licença de distribuição continua a cargo do proprietário.

## Droid Garage 1.2.0

Em 13/11/2026, `tools/generate_garage.py` produziu as peças PNG articuladas,
os manifestos e as vozes de Lumo, Vigia, Pico e Tranco. Os desenhos em 96 × 96
são construídos localmente com QPainter, com contornos, painéis, ópticas e juntas
próprios. Não incluem sprites, logotipos, gravações ou samples extraídos de outras
obras. O gerador é reproduzível e não é executado durante o uso do Companion.

As vozes são sínteses matemáticas PCM mono 22.050 Hz/16 bits, usando o compositor
existente com timbres e cadências individuais. Os efeitos comuns e os recursos
gráficos e sonoros dos três modelos anteriores permanecem preservados.
A definição de licença de distribuição segue a política do projeto acima.
