# Auditoría de `mood_rules.json` — falsos positivos del motor local

Book Classifier 3.20.1 · 19-08-2026 · 150 temas revisados

## El caso que lo destapó

**Wicked Lovers — Mía Para Siempre** (Shayla Black), romántica de suspense **sin
tags**, salía como `Paranormal · Angeles y demonios`.

La causa no es el LLM: es el motor local de reglas (`ml_classifier.mood_tags`).
`normalize()` quita las tildes antes de aplicar la regex, así que
*"departamento de policía de **Los Ángeles**"* se convierte en `los angeles` y
casaba con la alternativa `\bangeles\b`. Ese era el **único** match de toda la
sinopsis.

## Cómo se ha auditado

43 frases señuelo —lenguaje corriente de romántica, negra e histórica, sin
contenido paranormal ni de género— pasadas por las 150 regex. Cada disparo es un
falso positivo reproducible.

---

## 1. `Paranormal · Angeles y demonios` — ARREGLADO en 3.20.1

El peor del fichero: **5 de los 43 señuelos** lo disparaban.

| Señuelo | Casaba con |
|---|---|
| "el departamento de policía de Los Ángeles" | `\bangeles\b` |
| "—¿Qué demonios haces aquí?" | `\bdemonios?\b` |
| "una sonrisa angelical" | `angelical` |
| "Ella era un ángel, siempre pendiente de los demás" | `\bangels?\b` |
| "El daemon del servidor" | `daemons?` |

**Qué se ha hecho:**

- Guardas de contexto: `(?<!los )\bangeles\b`,
  `(?<!que )(?<!como )(?<!donde )(?<!cual )\bdemonios?\b`,
  `(?<!un )(?<!mi )(?<!su )(?<!el )\bangels?\b`.
- Eliminados como disparadores por sí solos: `angelical` y `daemons?`.
- Añadidos marcadores fuertes que faltaban, para no perder aciertos:
  `nefilim` (grafía castellana), `arcangel`, `serafin`, `angel guardian`,
  `guardian angel`, `cazador de demonios`, `demon hunter`,
  `principe/rey/senor/reina de los demonios|infiernos`, `semidemonio`,
  `posesion demoniaca`, `pacto con el diablo`.
- La `desc` que ve el LLM ahora dice explícitamente qué **no** cuenta, para que
  no vuelva a ponerlo él en la segunda pasada.

11 casos verdaderos siguen casando (ángel caído, nefilim, arcángel, *fallen
angel*, "the demons of hell", *Ángeles y demonios*…). 20 casos nuevos en
`tests/test_book_classifier_temas_vocab.py`, que pasa con **45 OK, 0 fallos**.

**Limitación que queda:** el nombre propio *Ángeles* ("Su madre, Ángeles, …")
sigue disparando. No hay guarda barata que lo distinga y es raro en sinopsis.

---

## 2. Los demás falsos positivos encontrados (sin tocar todavía)

Ordenados por lo frecuente que es la expresión en una biblioteca de romántica.

### Alta prioridad

| Tema | Alternativa | Falso positivo real |
|---|---|---|
| `Paranormal · Fae/Feerico` | `hadas`, `\bhada\b`, `duende` | **"un cuento de hadas"** (comunísimo en romántica), "hada madrina", "tiene mucho duende" |
| `Arquetipo · Realeza` | `principe`, `princesa` | **"su príncipe azul"**, "ven aquí, princesa" como apelativo cariñoso |
| `Subgenero · Thriller legal` | `\bjuicios?\b` | **"perder el juicio"** (= la cordura), **"a mi juicio"** (= en mi opinión) |
| `Tono · Trauma/Salud mental` | `\bduelo\b` | **"batirse en duelo"** — dispara en toda la histórica y la fantasía |
| `Paranormal · Sirenas` | `sirena`, `sirenas` | **"las sirenas de la policía"**, sirena de barco/fábrica — dispara en la novela negra |
| `Paranormal · Lobos/Shifters` | `lobos?` | **"un lobo solitario"**, "lobo de mar" |

Todos tienen guarda barata del mismo estilo que la de ángeles:
`cuento de hadas` → `(?<!cuento de )hadas`; `principe azul` y `mi/su princesa`
como lookbehind; `juicio` → exigir contexto (`sala de vistas`, `banquillo`,
`ir a juicio`, `jurado`) en vez del término suelto; `(?<!en )\bduelo\b`;
`(?<!las )sirenas de` … o exigir `sirena` junto a mar/cola/canto.

### Media

| Tema | Alternativa | Falso positivo |
|---|---|---|
| `Subgenero · Policiaco/Detective` | `asesinato`, `inspector` | cualquier libro con un crimen de fondo; "inspector de Hacienda" |
| `Arquetipo · Vaquero/Western` | `rancho` | ambientación rural sin nada de western |
| `Arquetipo · Medico/Hospital` | `enfermer[oa]` | profesión secundaria mencionada de pasada |
| `Ambientacion · Navideno/Festivo` | `navidad` | "la magia de las navidades" como metáfora |

### Irreducibles con regex (no merece la pena tocar)

`Paranormal · Dragones` ("un dragón de peluche"), `Paranormal · Vampiros`
("vestía de negro como un vampiro"), `Paranormal · Brujas/Magos` ("es una bruja",
como insulto). Aquí el término **es** el término; solo el LLM, que ve la frase
entera, puede distinguir. La vía correcta es afinar la `desc` para que la
segunda pasada los retire, no mutilar la regex.

---

## 3. Recomendación de método

El patrón que se repite: **una alternativa de una sola palabra que en castellano
tiene un uso figurado o toponímico muy común**. Antes de añadir un término suelto
a una regex conviene preguntarse si aparece en una frase hecha. Cuando la
respuesta es sí, hay tres salidas por orden de preferencia:

1. Sustituirlo por el sintagma que sí es unívoco (`angel caido`, `sala de vistas`).
2. Ponerle una guarda `(?<!...)` con las dos o tres colocaciones que lo estropean.
3. Dejarlo solo para el LLM (`"$^"`) con una `desc` que lo explique.

Nota técnica: `re` de Python exige lookbehind de **ancho fijo**, así que las
guardas van encadenadas —`(?<!que )(?<!como )`— y no como una alternancia dentro
de un solo `(?<!...)`.
