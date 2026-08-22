# Auditoría de `mood_rules.json` — falsos positivos del motor local

Book Classifier **3.20.3** · 19-08-2026 · 151 temas
Medido sobre `_datos_ejemplo/sample.csv` = **17.763 libros reales**

---

## Resumen: qué ha cambiado

| Tema | Libros antes | Después | Δ |
|---|---:|---:|---:|
| `Paranormal · Angeles y demonios` | 601 | 502 | −99 |
| `Paranormal · Lobos/Shifters` | 408 | 319 | −89 |
| `Paranormal · Fae/Feerico` | 257 | 167 | −90 |
| `Tono · Trauma/Salud mental` | 286 | 257 | −29 |
| `Subgenero · Thriller legal` | 162 | 133 | −29 |
| `Arquetipo · Realeza` | 82 | 79 | −3 |
| `Paranormal · Sirenas` | 27 | 26 | −1 |
| `Paranormal · Omegaverse` | 12 | 18 | **+6** |
| `Arquetipo · Alpha male` (nuevo) | — | 45 | **+45** |

**340 etiquetas de tema retiradas** de la biblioteca, más 51 recolocadas donde
corresponde. 94 comprobaciones en `tests/test_book_classifier_temas_vocab.py`.

---

## Dos cosas que hay que tener presentes

**1. El motor local ve las TAGS, no solo la sinopsis.** `ml_jobs.py` monta
`título + tags + comentarios + serie` (+ subtítulo) y se lo pasa entero a
`clf.classify()`. Una tag basta para disparar un tema aunque la sinopsis no
diga nada del asunto.

**2. `normalize()` quita las tildes** antes de aplicar la regex. Por eso
*"Los Ángeles"* se convierte en `los angeles`.

---

## Los dos casos que lo destaparon

### `Paranormal · Angeles y demonios` — *Wicked Lovers · Mía Para Siempre*

Romántica de suspense **sin tags**. *"departamento de policía de Los Ángeles"*
→ `los angeles` → casaba con `\bangeles\b`. Único match de toda la sinopsis.

| Señuelo | Casaba con |
|---|---|
| "policía de Los Ángeles" | `\bangeles\b` |
| "—¿Qué demonios haces aquí?" | `\bdemonios?\b` |
| "una sonrisa angelical" | `angelical` |
| "Ella era un ángel" | `\bangels?\b` |
| "El daemon del servidor" | `daemons?` |

### `Paranormal · Lobos/Shifters` — *Bachelor Brothers of Sydney · Bought at Auction*

Contemporánea, por la **tag** `Themes.Alpha Male`: `\balpha\b` estaba suelto.

- `alpha` aportaba **117 de los 408** aciertos del tema.
- **90 libros** tenían `alpha` y **ningún otro** marcador de cambiaformas:
  *"alpha billionaire romance"*, *"MC romance with alpha male bikers"*,
  *"an obsessive alpha husband"*, *"alpha hero to the nth degree"*.

Cuando `alpha` era lo único presente, casi siempre se equivocaba. Se sustituye
por compuestos inequívocos (`alpha wolf`, `pack alpha`, `alphas of the pack`,
`lobo alfa`, `alfa de la manada`, `bear/lion/dragon/tiger alpha`). Los que sí
eran del género los recoge `Omegaverse` (`mpreg`, `alpha king`, proximidad
alpha↔omega, con guarda para el *"alpha and the omega"* bíblico).

**Tema nuevo `Arquetipo · Alpha male`** (45 libros) para el héroe dominante de
la contemporánea, que es lo que la tag quería decir. Es un tema, no una
estantería: no obliga a reentrenar `model_weights.json`.

---

## Los seis de la auditoría

### `Paranormal · Fae/Feerico` — el más ruidoso (257 → 167)

`fairy` sin guarda se comía **todos los cuentos de hadas** de la biblioteca:

- *"a fairy tale for grown-ups"*, *"someone else's fairytale"*, *"based on the
  fairy tale Cinderella"* → `fairy(?! ?tales?)`
- *"the tooth fairy and her loathsome imps"* → `(?<!tooth )fairy`
- *"Santa's elves"* (24 libros navideños) → `(?<!santas )\belves\b`
- *"un cuento de hadas cautivador"* → `(?<!cuento de )(?<!cuentos de )\bhadas\b`
- *"escriduende 2014"*, "tener duende" → solo `\bduendes\b` en plural
- *"pixie cut"* (el corte de pelo) → `pixie(?! cut)`

Un retelling de cuento tiene su propio tema, `Subgenero · Retelling de cuento`;
es ahí donde deben caer.

### `Tono · Trauma/Salud mental` (286 → 257)

- **`depression` cazaba "the Great Depression"** y `depresion` "la gran
  depresión" — 38 novelas de los años 30 marcadas como salud mental.
- **`adiccion` no tenía `\b` y casaba dentro de "contr-adiccion-es"**:
  *"las contradicciones de la historia argentina"*. Además *"crean adicción"*
  es reclamo de contraportada, no una trama sobre adicción.
- `\bduelo\b` ← *"se enfrentarán cara a cara en un duelo singular"* (a espada).

Se conservan *"tratamiento de las adicciones sexuales"* y *"aún de duelo por el
asesinato de su hijo"*.

### `Subgenero · Thriller legal` (162 → 133)

`\bjuicios?\b` disparaba con las tres acepciones no jurídicas del castellano:

- **opinión**: *"según un juicio de Walter Benjamin"*, *"el juicio de George Steiner"*
- **cordura / valoración**: *"poner en tela de juicio"*
- **religioso**: *"el día del juicio final"*

Se sustituye por las formas que sí son un proceso (`ir/llevar a juicio`,
`a juicio por`, `juicio oral/penal/civil/militar`, `juicio al|contra`,
`sala de vistas`, `banquillo de los acusados`, `jurado popular`). `tribunal`
suelto también caía con *"el tribunal de la realidad"*; ahora pide complemento
(`de justicia`, `supremo`, `de primera instancia`…) o el plural `tribunales`.

### `Arquetipo · Realeza` (82 → 79)

`principe(?!s? azul)` y `(?<!mi )(?<!su )princesa`, para *"no es exactamente un
príncipe azul"* y *"mi princesa"* como apelativo. Poco volumen: en tu biblioteca
la mayoría de los `príncipe` son de novela histórica y **sí** son realeza.

### `Paranormal · Sirenas` (27 → 26)

Guarda para la sirena de policía / ambulancia / bomberos / niebla. En tus datos
apenas aparecía, pero es prevención barata.

> Detalle técnico que costó un test en rojo: la guarda tiene que ir tras `\b`
> —`\bsirenas?\b(?! de la policia)`—. Sin el `\b` final, "sirenas" casa como
> `sirena` + `s`, el lookahead mira `"s de la policia"` y la guarda nunca se
> aplica.

### `Paranormal · Lobos/Shifters` — apellidos (319, −1)

Guardas para *"lobo de mar"*, *"lobo solitario"* y *"el niño lobo"*.

**Lo que NO tiene arreglo por regex:** `\bwolf\b` como **apellido** — *"the
notorious bandit Jack Wolf"*, *"the man who calls himself Fenris Wolf"* — y
`lobo` como apellido español (*"Marc Lobo, un hombre que la incomoda"*).
`normalize()` pasa todo a minúsculas, así que no queda ni la pista de la
mayúscula. Son ~15 libros. Esto solo lo puede deshacer el LLM en la segunda
pasada, que sí ve la frase entera.

---

## Residuo conocido en Ángeles y demonios

La autora **Ángeles Caso** sigue disparando el tema (12 libros con
`(?<!los )\bangeles\b`). Distinguir un nombre propio de una criatura celestial
no se puede hacer sin contexto. Igual que los apellidos de arriba: territorio
del LLM, no de la regex.

---

## Regla de método

El patrón es siempre el mismo: **una alternativa de una sola palabra que en
castellano o en inglés tiene un uso figurado, toponímico o de apellido muy
común**. Antes de meter un término suelto en una regex conviene preguntarse si
aparece en alguna frase hecha. Cuando la respuesta es sí, tres salidas por orden
de preferencia:

1. El sintagma que sí es unívoco: `angel caido`, `pack alpha`, `sala de vistas`.
2. Una guarda `(?<!...)` / `(?!...)` con las dos o tres colocaciones que lo
   estropean.
3. Dejarlo solo para el LLM (`"$^"`) con una `desc` que lo explique.

Y **medir siempre sobre `sample.csv` antes de dar por bueno el cambio**: los
`fairy tale` y las `contradicciones` no se ven leyendo la regex, solo contando.

### Notas técnicas

- `re` de Python exige lookbehind de **ancho fijo**: las guardas van encadenadas
  —`(?<!que )(?<!como )`— y nunca como alternancia dentro de un solo `(?<!...)`.
- Un `?` opcional delante de un lookahead lo anula (el caso `sirenas?`). Cierra
  con `\b` antes de la guarda.
- Las `desc` también se han actualizado: son lo único que ve el LLM en la
  segunda pasada, así que ahora dicen explícitamente qué **no** cuenta. Si solo
  se arregla la regex, el LLM vuelve a poner el tema por su cuenta.

---

## Y lo de siempre

Arreglar las reglas **no reclasifica lo ya etiquetado**. Hay que reprocesar los
libros afectados para que se limpien.
