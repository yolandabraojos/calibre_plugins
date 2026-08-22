# Book Classifier — Documentación de comportamiento del plugin

**Versión:** 3.5.0
**Plataformas:** Windows · macOS · Linux
**Calibre mínimo:** 5.0.0

---

## Índice

1. [Arquitectura general](#1-arquitectura-general)
2. [Los dos ejes de clasificación](#2-los-dos-ejes-de-clasificación)
3. [Motor IA local (`ml_classifier.py`)](#3-motor-ia-local-ml_classifierpy)
4. [Los niveles de decisión de librería](#4-los-niveles-de-decisión-de-librería)
5. [Reparto en chunks/jobs (`plan_classify_chunks`)](#5-reparto-en-chunksjobs-plan_classify_chunks)
6. [Escritura de campos y fusión con lo existente](#6-escritura-de-campos-y-fusión-con-lo-existente)
7. [Rescate con IA en la nube (capa híbrida opcional)](#7-rescate-con-ia-en-la-nube-capa-híbrida-opcional)
8. [Coherencia entre copias (`coherence.py`)](#8-coherencia-entre-copias-coherencepy)
9. [Menú del plugin](#9-menú-del-plugin)
10. [Configuración (`prefs`)](#10-configuración-prefs)
11. [Limitaciones conocidas y decisiones deliberadas](#11-limitaciones-conocidas-y-decisiones-deliberadas)

---

## 1. Arquitectura general

```
action.py                ← InterfaceAction: menú, orquestación, jobs
  ├─ ml_jobs.py           ← Clasificación local (planificación + tarea + fusión)
  │    └─ ml_classifier.py← Modelo IA puro Python (TF-IDF + regresión logística)
  ├─ llm_jobs.py           ← Rescate con IA en la nube (planificación + tarea)
  │    └─ llm_rescue_engine.py ← Llamadas HTTP a proveedores LLM (urllib puro)
  └─ config.py             ← Preferencias persistentes + diálogo de configuración

model_weights.json  ← Modelo entrenado (vocabulario TF-IDF + coeficientes), ~5.5 MB
mood_rules.json      ← Reglas regex de palabras clave para tags de tema
```

El modelo y las reglas se buscan en este orden: carpeta de configuración de
Calibre (para poder actualizarlos sin reinstalar el plugin) → paquete Python
→ recursos del ZIP instalado (`plugin.load_resources`, el método fiable
cuando Calibre carga el plugin desde el ZIP) → fichero junto al módulo (solo
para pruebas fuera de Calibre).

---

## 2. Los dos ejes de clasificación

- **Eje 1 — Librería** (excluyente): una única librería por libro, de un
  conjunto de 6 clases fijas en el modelo local (`model_weights.json`):
  `Romance contemporáneo`, `Romance histórico`, `Romantasy / Paranormal`,
  `Fantasía & Sci-Fi`, `Misterio·Thriller·Terror`, `Ficción general`.
- **Eje 2 — Tema** (multi-etiqueta): tags de tono/tropo (`Tema: Vampiros`,
  `Tema: Mafia`, `Tema: Slow burn`…), independientes de la librería. El motor
  local las detecta por regex bilingües sobre el texto normalizado; el LLM las
  elige razonando, pero **solo ve los NOMBRES** del vocabulario, nunca la
  regex. Desde 3.10.0 cada tema de `mood_rules.json` puede ser un objeto
  `{"regex": ..., "desc": ...}`: la descripción viaja al prompt como
  `Nombre — descripción` y es lo único que desambigua un tema para la IA. El
  formato antiguo (valor = la regex a secas) se sigue aceptando, y entonces la
  descripción va vacía. Una regex imposible (`"$^"`) define un tema que **solo**
  puede aplicar el LLM, sin tocar el motor local ni el modelo.

**Importante:** el rescate con IA en la nube (§7) usa una taxonomía DISTINTA
y más fina de 9 categorías (separa `Romantasy` de `Paranormal`, y `Fantasía`
de `Ciencia Ficción`, añade `No-Ficción`). Un libro rescatado por la IA puede
por tanto recibir un valor de librería que el modelo local nunca produciría
directamente. Si se homogeneiza la taxonomía de un lado, hay que revisar el
otro (`llm_rescue_engine.LIBRERIAS` vs `model_weights.json["classes"]`).

**Dos campos separados (desde 3.5.0):** la clasificación final vive en
`ml_library_field` (por defecto `tags`/`Biblioteca: `, la de siempre). El
resultado CRUDO del rescate con IA vive en un campo PROPIO y separado,
`llm_library_field` (por defecto `#libreria_ia`) — el rescate NUNCA escribe
ya en `ml_library_field`. La clasificación local puede LEER ese campo
dedicado y promover su valor al campo principal si la confianza es muy alta
(§4, nivel 0), pero nunca escribe en él. Ver §6 y §9.

---

## 3. Motor IA local (`ml_classifier.py`)

- **Normalización de texto** (`normalize()`): unescape HTML → quita etiquetas
  HTML → quita apóstrofes (no los convierte en espacio, para no partir
  "world's" en "world" + "s" suelto) → NFKD sin diacríticos → minúsculas →
  solo `[a-z0-9/\- ]`. **Debe coincidir exactamente** con
  `scripts/train_book_classifier.py::normalize`; si se cambia una copia hay
  que cambiar la otra y reentrenar.
- **Vectorización**: unigramas + bigramas de palabras, TF sublineal
  `1 + log(count)`, ponderado por IDF precalculado, normalización L2 —
  reproduce el pipeline TF-IDF de scikit-learn sin depender de la librería.
- **Predicción**: regresión logística multiclase (`intercept + Σ coef·tfidf`)
  con softmax para la confianza. Si el texto no aporta ningún término
  conocido por el vocabulario, devuelve `(None, 0.0)` — se traduce más tarde
  en `(sin datos)`.
- **Tags de tema**: cada entrada de `mood_rules.json` es un regex; se marca
  el tema si el regex matchea el texto normalizado. Puede devolver varias o
  ninguna.

---

## 4. Los niveles de decisión de librería

Ejecutados en este orden, cada uno solo actúa sobre lo que el anterior no
resolvió (salvo el nivel 0, que puede ser sobreescrito por el consenso de
grupo — ver más abajo):

0. **Promoción desde la IA en la nube** *(opcional, `llm_promote_enabled`,
   por defecto activado)*. Antes de la predicción individual, se lee
   -nunca se escribe- el campo dedicado del rescate LLM
   (`llm_library_field`, ver §7) y su confianza (`llm_conf_field`, entero
   0-100). Si hay valor y su confianza/100 supera `llm_promote_threshold`
   (por defecto 0.90 — deliberadamente más estricto que `llm_min_conf`,
   0.55, que solo decide si el rescate resuelve el residuo), se usa ese
   valor tal cual como clasificación del libro (confianza no incierta).
   Sigue pudiendo ser sobreescrito por el consenso de grupo (nivel 2) si el
   resto de la serie tira hacia otra librería con más confianza acumulada —
   misma filosofía que con una predicción individual bien clasificada (ver
   §10). El campo dedicado de la IA NUNCA se escribe desde aquí.
1. **Predicción individual.** Si la confianza del modelo supera el umbral
   configurado (`ml_threshold`, por defecto 0.55), se usa tal cual.
2. **Consenso de grupo** (dentro de `run_classify_chunk_task`, por cada
   `subgroup`): los libros se agrupan por `#universe` si tiene valor, si no
   por `series`. Dentro del grupo, se suma la confianza de todas las
   predicciones individuales *no inciertas* por librería, y gana la librería
   con mayor confianza acumulada — **no la más votada**, la de mayor suma de
   confianza. Esa librería se aplica a TODOS los libros del grupo, incluidos
   los que individualmente habían quedado inciertos. Se puede desactivar
   (`ml_group_unify=False`) o cambiar el campo de universo
   (`ml_universe_field`, por defecto `#universe`, no `#world` — distinto del
   campo `#world` que usa `fix_metadata`).
3. **Consenso de autor** (`run_author_fallback_task`, aparte, tras terminar
   TODOS los jobs de clasificación): para los libros que sigan
   `[REVISAR]`/`(sin datos)`, mira qué librería domina entre los OTROS libros
   YA resueltos del mismo autor (dentro del mismo lote `book_ids` que se
   lanzó). Solo asigna si el autor tiene al menos `ml_author_min_books`
   *(nota: la clave real en `settings` es la que define `config.py`, con
   default `author_min_books=3` embebido en el propio job — revisar si se
   expone en la UI)* libros resueltos y la librería dominante alcanza
   `ml_author_dominance` (por defecto 0.6, es decir 60%) de esos libros.

Si ningún nivel resuelve, el libro queda como `[REVISAR]` (había predicción
pero de baja confianza) o `(sin datos)` (no había texto útil que analizar).

**Por qué el orden importa:** el consenso de grupo se calcula DENTRO de cada
subgrupo por separado, nunca mezclando series/universos distintos aunque
compartan el mismo job — ver §5. El consenso de autor se hace en una pasada
final porque necesita leer de la BD los resultados YA escritos por los jobs
de clasificación anteriores (no puede correr en paralelo con ellos).

---

## 5. Reparto en chunks/jobs (`plan_classify_chunks`)

Antes de lanzar los `ThreadedJob`, se agrupan los `book_ids` por serie/
universo (lectura rápida en el hilo de la GUI) y se reparten en chunks:

- Cada serie/universo se mantiene **entera** dentro de un mismo chunk (el
  consenso de grupo necesita verla completa), pero un chunk puede contener
  varias series/universos pequeños juntos.
- El tamaño de referencia es `ai_batch_ref` (reutiliza la misma cifra que el
  tamaño de lote del rescate LLM como unidad de medida, aunque esta
  clasificación es 100% local y no llama a ningún proveedor). Los chunks
  apuntan a ese tamaño y no superan el doble, salvo que una sola serie ya sea
  más grande — entonces ocupa su propio chunk igualmente (no se puede partir
  sin romper el consenso).
- Los libros sueltos (sin serie/universo) rellenan el hueco sobrante de los
  chunks de grupos y, lo que sobre, se reparte en chunks propios sin
  consenso entre ellos.

---

## 6. Escritura de campos y fusión con lo existente

`_merge_prefixed()` decide cómo combinar el nuevo valor con lo que ya hay en
el campo destino:

- `overwrite=True` (por defecto): quita SOLO los valores previos que
  empiecen por el prefijo del plugin (`Biblioteca: `, `Tema: `) y los
  reemplaza; el resto de tags/valor del campo se conserva intacto.
- `overwrite=False`: añade sin duplicar, sin tocar nada existente.

Si el campo destino es `tags` (o cualquier columna multivalor), el resultado
es una lista; si es una columna de texto simple, se unen con `, `.

Los prefijos solo se aplican cuando el campo destino ES `tags`
(`lib_prefix_eff`/`mood_prefix_eff` quedan vacíos si se manda a una columna
dedicada como `#libreria`) — así el prefijo `Biblioteca:` no ensucia una
columna que ya es exclusivamente para eso.

**El campo dedicado de la IA (`llm_library_field`, §7) sigue la misma regla
de fusión** pero con un único escritor: solo `llm_jobs.run_rescue_batch_task`
escribe ahí (`llm_library_prefix`, efectivo solo si el campo es `tags`). El
nivel 0 de `ml_jobs.py` (§4) lo LEE para promocionar su valor al campo
principal, pero nunca pasa por `_merge_prefixed` sobre ese campo — no lo
toca en absoluto.

---

## 7. Rescate con IA en la nube (capa híbrida opcional)

Capa totalmente opcional, solo se activa desde el menú "Rescatar con IA...".
Sirve para resolver los libros que quedaron `[REVISAR]`/`(sin datos)` tras la
clasificación local, mandándolos a un LLM externo.

- **Proveedores soportados**: GLM (por defecto), DeepSeek, OpenAI, Google
  (Gemini vía endpoint compatible OpenAI), Kimi, Qwen, un endpoint local
  (Ollama), y Anthropic (única API con formato distinto: `/v1/messages`, el
  resto usan el formato `/chat/completions` de OpenAI). Sin dependencias
  externas: HTTP puro con `urllib`.
- **Selección de candidatos** (`select_rescue_candidates`): filtra a los
  libros con residuo `[REVISAR]`/`(sin datos)` en el campo de librería (o
  TODOS si `force_all`, usado por "Reevaluar con IA la selección"). Excluye
  del texto de contexto las tags que serían una "fuga" (`_is_leak_tag`): el
  propio grupo `Género`/`Biblioteca`/`Libreria` en formato canónico de
  `fix_metadata`, o los prefijos crudos pre-`fix_metadata` — para que la IA
  no se limite a repetir una etiqueta de género ya puesta (a veces mal) en
  vez de razonar sobre la sinopsis. Las demás tags canónicas (Subgénero,
  Ambientación, Tono...) SÍ se mandan: son señal de contenido derivada del
  texto, no un eco de la clase.
- **No se repite lo ya rescatado (desde 3.6.0)**: el filtro de residuo mira
  el campo PRINCIPAL (`ml_library_field`), donde el rescate no escribe nunca
  (§«Campo de la librería»), así que un libro rescatado ayer seguía con
  `[REVISAR]` ahí y se volvía a mandar al LLM en cada pasada. Ahora también se
  comprueba `llm_library_field`: si ya tiene un valor resuelto, el libro se
  omite. «Reevaluar con IA» (`force_all`) lo sigue reprocesando a propósito.
- **Deduplicación**: libros con mismo autor+título+idioma (normalizado) se
  agrupan y se manda a la IA solo el representante con la sinopsis más larga;
  el resultado se aplica luego a todas las copias del grupo. Ahorra llamadas
  en bibliotecas con duplicados.
- **Índice de donantes de la biblioteca (desde 3.6.0)**: la deduplicación
  anterior solo agrupa DENTRO de la tanda. Antes de lanzar ningún job,
  `action._prefetch_donor_index` recorre la biblioteca ENTERA (lectura en lote
  con `all_field_for`, en el hilo de la GUI: el job no puede tocar la BD) y
  monta un índice `título+autor → librería`. Los candidatos que ya tienen
  respuesta ahí se resuelven copiándola (`resolve_from_index`), sin gastar una
  llamada. El resultado se aplica con el MISMO código que el del LLM
  (`apply_llm_result`), así que no pueden divergir.
  - **Clave de identidad** (`book_key`): primer autor normalizado con sus
    palabras ORDENADAS —para que `Sanderson, Brandon` y `Brandon Sanderson`
    colisionen—, título sin acentos/puntuación, e idioma. Solo el primer autor:
    el orden de los demás varía entre copias.
  - **Dos niveles**. La clave ESTRICTA (título completo) copia librería, temas,
    serie y % de confianza. La clave LAXA (sin subtítulo tras `:` ni sufijo
    `(Saga X, 2)`) copia SOLO la librería, y solo si TODOS los donantes de esa
    clave coinciden: los tomos de una saga comparten género pero no temas, y
    dos títulos distintos que empiecen igual (`Star Wars: ...`) se anulan entre
    sí en cuanto discrepan. Las cifras finales no se tocan nunca: `Dune 2` y
    `Dune 3` no deben colapsar.
  - **Donantes de dos orígenes**: `llm_library_field` (respuesta previa de la
    IA) se copia con su confianza; `ml_library_field` (clasificador local)
    también vale como respuesta pero se copia SIN confianza a propósito — el
    nivel 0 de promoción (§4) solo asciende un valor de la IA si supera
    `llm_promote_threshold`, así que sin confianza no puede cerrarse el bucle
    local → campo IA → promoción al campo local.
  - **Auditable**: los copiados llevan en `#motivo_ia` el id del donante y el
    nivel de coincidencia, y el informe final los cuenta aparte.
- **Prompt** (`build_batch_prompt`): incluye reglas de desambiguación muy
  detalladas para los pares conflictivos Fantasía/Ciencia Ficción y
  Romantasy/Paranormal/Romance histórico (ver comentarios inline en
  `llm_rescue_engine.py` — no se resumen aquí porque son la lógica de negocio
  central del prompt y cambian con cierta frecuencia). Si `llm_write_serie`
  está activo, pide también la saga/serie detectada.
- **Umbral de confianza** (`llm_min_conf`, por defecto 0.55): si la IA
  devuelve confianza por debajo, el libro se deja en `(revisar)` igualmente
  aunque haya dado una opinión — pero el motivo y el % de confianza SÍ se
  guardan si están activados, para poder analizar el residuo. De ahí el caso
  típico: `#motivo_ia` y `#confianza_ia` rellenos con `#libreria_ia` VACÍO.
  Los temas SÍ se escriben desde 3.9.0 (ver abajo): ya no dependen de que la
  librería quede resuelta.
- **Campo propio para los temas de la IA** (`llm_temas_field`, por defecto
  `#temas_ia`, desde 3.9.0): el rescate escribe sus temas en una columna
  SEPARADA de la del motor local (`ml_mood_field`), igual que ya hacía con la
  librería (`#libreria_ia`). Antes escribía en el mismo campo y, con
  `ml_overwrite` activo, borraba los `Tema: ` que había puesto el motor local
  por regex, sin dejar rastro de cuál venía de dónde. Con los dos campos se
  pueden comparar y usar las diferencias para mejorar los patrones de
  `mood_rules.json`. Dos consecuencias:
  - los temas se guardan aunque la librería quede `(revisar)`, porque ya no
    contaminan la clasificación (antes colgaban del mismo `if resolved`);
  - la columna debe EXISTIR antes de rescatar: se valida junto con
    `llm_library_field` y, si falta, el rescate no arranca (así no se gastan
    llamadas cuyo resultado no se podría escribir).
  Dejar `llm_temas_field` VACÍO restaura el comportamiento anterior.
- **Reconocimiento del nombre del tema** (`norm_temas`, desde 3.10.0): mismo
  problema y misma solución que con la librería. Antes se comparaba con
  `.lower()` a secas contra el nombre exacto, así que `Subgénero · Fantasía
  urbana` —con las tildes que pone cualquier modelo que escriba bien español—,
  `Subgenero: Fantasia urbana` o `Fantasia urbana` a secas se descartaban EN
  SILENCIO y el libro parecía no tener temas. Ahora se compara por clave
  normalizada (`_lib_key`) y, si no casa, por la HOJA del nombre (lo que va
  tras el `·`) y solo si es UNA.
- **Reconocimiento del nombre de la librería** (`norm_libreria`, desde 3.8.0):
  la respuesta se compara con el catálogo por una clave normalizada
  (`_lib_key`: sin acentos, sin puntuación, espacios colapsados), y si no hay
  coincidencia exacta se acepta la librería cuyo nombre aparezca **como tal**
  dentro de la respuesta, y solo si es UNA. Antes se comparaba con `.lower()`
  a secas, así que `Ciencia Ficcion` sin tilde, `Misterio/Thriller/Terror` o
  `No Ficcion` se descartaban EN SILENCIO y el libro parecía no tener
  respuesta cuando la IA sí había contestado. `Romance` a secas sigue siendo
  `(revisar)`: no distingue contemporáneo de histórico, que es justo la duda
  que hay que marcar; y `Fantasía o Ciencia Ficción` también, por ambiguo.
- **Causa del `(revisar)`** (desde 3.8.0): `classify_batch` devuelve además
  `causa` y `libreria_raw`, y el informe final desglosa por qué se quedó cada
  libro sin resolver — `umbral` (bajar `llm_min_conf` serviría), `declarado`
  (la IA dice que no tiene base), `nombre` (fuera del catálogo, con la lista
  de los nombres más repetidos), `sin_libreria` y `sin_respuesta` (el modelo
  no devolvió ese libro: lote truncado). Mezclarlas todas en un mismo
  `(revisar)` impedía saber cuál de las cuatro acciones tomar.
- **Reintentos**: en HTTP 429 espera el `Retry-After` de la cabecera si
  viene, si no espera de forma creciente (10, 20, 30... s, tope 60) — el tier
  gratuito de GLM limita por minuto y hay que esperar en serio, no solo unos
  segundos. En timeout/fallo de red, reintenta con espera corta creciente.
  Hasta 5 reintentos por defecto.
- **Parseo tolerante** (`parse_array`): quita cercos de código ```` ```json ````,
  repara comas colgantes, y si la respuesta viene truncada rescata los
  objetos JSON completos uno a uno ignorando el último a medias.
- **Reparto en jobs** (`plan_rescue_chunks`): los candidatos se reparten en
  chunks de hasta `2 × llm_batch`; cada job hace sus llamadas y aplica sus
  escrituras en cuanto termina, sin esperar a los demás — así los primeros
  resultados aparecen antes en bibliotecas grandes.
- **Campo de la librería (desde 3.5.0, campo PROPIO):** el resultado de la
  IA se escribe en `llm_library_field` (por defecto `#libreria_ia`), NUNCA
  en el campo principal de la clasificación local (`ml_library_field`). Solo
  se escribe cuando el libro queda resuelto (confianza ≥ `llm_min_conf`).
  Para que ese resultado llegue al campo principal hace falta el nivel 0 de
  promoción de `ml_jobs.py` (§4, umbral `llm_promote_threshold` propio y más
  estricto) — el rescate por sí solo ya no toca el campo principal.
- **Campos opcionales que puede rellenar** (todos con columna configurable):
  motivo (`#motivo_ia` por defecto), serie detectada (`#serie_ia`), % de
  confianza 0-100 (`#confianza_ia`). Motivo y confianza se guardan siempre
  que la IA responda algo para ese libro, aunque no llegue al umbral.

---

## 8. Coherencia entre copias (`coherence.py`)

Informe de solo lectura (menú «Revisar coherencia entre copias...», desde
3.7.0). Ni la clasificación local ni el rescate revisan jamás un valor ya
escrito: ambos deciden **libro a libro**, a partir de la sinopsis de ESE
registro. Dos copias del mismo libro con sinopsis distintas —o una sin
sinopsis— pueden acabar en librerías distintas o con temas distintos sin que
nada lo detecte. Y desde 3.6.0 una copia ya clasificada actúa de **donante**
para las demás, así que un error se propaga en vez de quedarse quieto: este
informe es la contrapartida.

Agrupa por la MISMA clave de identidad que el índice de donantes
(`llm_jobs.book_key`: primer autor con las palabras ordenadas + título + idioma)
y saca cuatro hallazgos:

| Hallazgo | Qué es | Se arregla |
|---|---|---|
| 1. Contradicción de librería | Dos copias con librería distinta | A mano: una de las dos está mal |
| 2. Contradicción de temas | Conjuntos de temas incompatibles (ninguno contiene al otro) | A mano: hay que decidir cuál vale |
| 3. Temas incompletos | Los temas de unas copias son **subconjunto** de los de otras (incluida la copia sin ninguno) | Solo: botón «Unificar temas incompletos», que escribe la UNIÓN |
| 4. Clasificados sin ningún tema | Librería sí, temas no | Reclasificación local, o reevaluación con IA |

- El botón de unificar es deliberadamente el único que escribe, y solo actúa
  sobre el caso 3, donde **no hay nada que decidir**: si un conjunto contiene
  al otro, la unión es la respuesta y no puede perder información. Los casos
  1 y 2 son juicios, no fusiones, y el plugin no los toma por su cuenta.
- El hallazgo 4 era el hueco sistemático del plugin, no un error entre copias:
  hasta 3.9.0 los temas viajaban de paquete con la decisión de librería
  (`apply_llm_result` solo los escribía si el libro quedaba `resolved`). Desde
  3.9.0 van a su campo propio y se escriben aunque la librería no se resuelva,
  así que el hallazgo queda reducido a los libros clasificados con
  `llm_write_temas` desactivado.
- El informe HTML da por grupo una búsqueda `id:1 or id:2` para dejar ese
  grupo en pantalla en calibre. Se escribe en un temporal persistente y se
  abre con `open_local_file`.

---

## 9. Menú del plugin

| Acción | Qué hace |
|---|---|
| Clasificar libros seleccionados / TODA la biblioteca | Lanza la clasificación local (niveles 1-3, §4) |
| Rescatar con IA los no clasificados (selección / biblioteca) | Manda a la IA en la nube solo los `[REVISAR]`/`(sin datos)` |
| Reevaluar con IA la selección (ignora marcas) | Igual, pero manda TODOS los seleccionados aunque ya estén clasificados (`force_all`) |
| Revisar coherencia entre copias... | Informe de copias del mismo título+autor con clasificaciones que se contradicen (§8) |
| Limpiar clasificaciones del plugin (selección / biblioteca) | Quita las tags `Biblioteca:`/`Tema:` del plugin |
| Configurar plugin... | Abre el diálogo de preferencias (`config.py`) |

---

## 10. Configuración (`prefs`)

Persistida vía `JSONConfig('plugins/book_classifier')`. Claves relevantes y
sus valores por defecto:

| Clave | Default | Uso |
|---|---|---|
| `source_fields` | `['title','comments','tags']` | Campos que forman el texto de entrada al modelo |
| `ml_use_subtitle` / `ml_subtitle_field` | `True` / `#subtitle` | Añade el subtítulo al texto de entrada |
| `ml_library_field` / `ml_mood_field` | `tags` / `tags` | Campos destino de cada eje |
| `ml_library_prefix` / `ml_mood_prefix` | `'Biblioteca: '` / `'Tema: '` | Prefijos cuando el destino es `tags` |
| `ml_threshold` | `0.55` | Confianza mínima del modelo local (nivel 1) |
| `ml_overwrite` | `True` | Reemplaza tags previas del plugin en vez de solo añadir |
| `ml_group_unify` / `ml_group_unify_moods` | `True` / `True` | Activa el consenso de grupo (nivel 2) y unión de temas del grupo |
| `ml_universe_field` | `#universe` | Campo de universo para agrupar (si vacío, se usa `series`) |
| `ml_author_fallback` / `ml_author_dominance` | `True` / `0.6` | Activa el consenso de autor (nivel 3) y su umbral de mayoría |
| `llm_provider` / `llm_api_key` / `llm_model` | `glm` / `''` / `''` | Proveedor y credenciales del rescate IA |
| `llm_batch` / `llm_min_conf` | `10` / `0.55` | Libros por llamada y confianza mínima del rescate |
| `llm_write_temas` / `llm_write_reason` / `llm_write_serie` / `llm_write_conf` | `True` × 4 | Qué campos adicionales rellena el rescate |
| `llm_reason_field` / `llm_serie_field` / `llm_conf_field` | `#motivo_ia` / `#serie_ia` / `#confianza_ia` | Columnas destino de esos campos |
| `llm_library_field` / `llm_library_prefix` | `#libreria_ia` / `'Biblioteca IA: '` | Campo PROPIO donde el rescate escribe su librería (nunca en `ml_library_field`); el prefijo solo se aplica si el campo es `tags` |
| `llm_temas_field` / `llm_temas_prefix` | `#temas_ia` / `'Tema IA: '` | Campo PROPIO donde el rescate escribe sus temas (nunca en `ml_mood_field`); el prefijo solo se aplica si el campo es `tags`. VACÍO = comportamiento anterior a 3.9.0 (escribir en `ml_mood_field`) |
| `llm_promote_enabled` / `llm_promote_threshold` | `True` / `0.90` | Nivel 0 (§4): promueve el valor de `llm_library_field` al campo principal si su confianza (`llm_conf_field`/100) supera este umbral. Solo lee `llm_library_field`, nunca escribe en él |

---

## 11. Limitaciones conocidas y decisiones deliberadas

- El modelo local tiene 6 clases fijas; para cambiar las categorías hay que
  reentrenar (`scripts/train_book_classifier.py`) y regenerar
  `model_weights.json` — no es una lista configurable en `prefs`.
- La taxonomía de 9 categorías del rescate LLM (§2) NO coincide 1:1 con las 6
  del modelo local; es intencional (más granularidad quirúrgica para los
  casos dudosos que el modelo local no distingue bien: Romantasy vs
  Paranormal, Fantasía vs Sci-Fi), pero significa que tras el rescate pueden
  convivir en la biblioteca valores de `Biblioteca:` de ambas taxonomías.
- El consenso de grupo (nivel 2) puede "contaminar" un libro individualmente
  bien clasificado si el resto de la serie tira hacia otra librería con más
  confianza acumulada — es una decisión deliberada (coherencia de serie por
  encima de la predicción individual), documentada en la UI como "Misma
  librería para toda la serie/universo".
- El campo de universo por defecto del clasificador (`#universe`) es
  distinto del campo `#world` que usa `fix_metadata` para lo mismo
  conceptualmente — si se quiere que ambos plugins compartan el mismo dato,
  hay que igualar `ml_universe_field` a `#world` a mano en la configuración.
- El rescate con IA requiere conexión y clave de API; el resto del plugin
  (clasificación local, niveles 0-3) funciona sin internet — el nivel 0 solo
  LEE datos que un rescate anterior ya haya dejado en `llm_library_field`,
  no llama a ningún proveedor por sí mismo.
- El umbral de promoción (`llm_promote_threshold`, 0.90 por defecto) es
  deliberadamente más alto que `llm_min_conf` (0.55): este último decide si
  el rescate resuelve un residuo (queda como "clasificación de la IA"),
  mientras que promocionar ese valor al campo principal es una decisión más
  fuerte y debe reservarse a los casos en que la IA está muy segura.
- Sin límite de tamaño de biblioteca conocido, pero bibliotecas muy grandes
  generan muchos `ThreadedJob` en paralelo (uno por chunk); Calibre los
  encola internamente.
