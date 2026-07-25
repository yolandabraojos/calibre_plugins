# Book Classifier — Documentación de comportamiento del plugin

**Versión:** 3.4.1
**Plataformas:** Windows · macOS · Linux
**Calibre mínimo:** 5.0.0

---

## Índice

1. [Arquitectura general](#1-arquitectura-general)
2. [Los dos ejes de clasificación](#2-los-dos-ejes-de-clasificación)
3. [Motor IA local (`ml_classifier.py`)](#3-motor-ia-local-ml_classifierpy)
4. [Los tres niveles de decisión de librería](#4-los-tres-niveles-de-decisión-de-librería)
5. [Reparto en chunks/jobs (`plan_classify_chunks`)](#5-reparto-en-chunksjobs-plan_classify_chunks)
6. [Escritura de campos y fusión con lo existente](#6-escritura-de-campos-y-fusión-con-lo-existente)
7. [Rescate con IA en la nube (capa híbrida opcional)](#7-rescate-con-ia-en-la-nube-capa-híbrida-opcional)
8. [Menú del plugin](#8-menú-del-plugin)
9. [Configuración (`prefs`)](#9-configuración-prefs)
10. [Limitaciones conocidas y decisiones deliberadas](#10-limitaciones-conocidas-y-decisiones-deliberadas)

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
  `Tema: Mafia`, `Tema: Slow burn`…), detectadas por regex bilingües sobre el
  texto normalizado, independientes de la librería.

**Importante:** el rescate con IA en la nube (§7) usa una taxonomía DISTINTA
y más fina de 9 categorías (separa `Romantasy` de `Paranormal`, y `Fantasía`
de `Ciencia Ficción`, añade `No-Ficción`). Un libro rescatado por la IA puede
por tanto recibir un valor de librería que el modelo local nunca produciría
directamente. Si se homogeneiza la taxonomía de un lado, hay que revisar el
otro (`llm_rescue_engine.LIBRERIAS` vs `model_weights.json["classes"]`).

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

## 4. Los tres niveles de decisión de librería

Ejecutados en este orden, cada uno solo actúa sobre lo que el anterior no
resolvió:

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
- **Deduplicación**: libros con mismo autor+título+idioma (normalizado) se
  agrupan y se manda a la IA solo el representante con la sinopsis más larga;
  el resultado se aplica luego a todas las copias del grupo. Ahorra llamadas
  en bibliotecas con duplicados.
- **Prompt** (`build_batch_prompt`): incluye reglas de desambiguación muy
  detalladas para los pares conflictivos Fantasía/Ciencia Ficción y
  Romantasy/Paranormal/Romance histórico (ver comentarios inline en
  `llm_rescue_engine.py` — no se resumen aquí porque son la lógica de negocio
  central del prompt y cambian con cierta frecuencia). Si `llm_write_serie`
  está activo, pide también la saga/serie detectada.
- **Umbral de confianza** (`llm_min_conf`, por defecto 0.55): si la IA
  devuelve confianza por debajo, el libro se deja en `(revisar)` igualmente
  aunque haya dado una opinión — pero el motivo y el % de confianza SÍ se
  guardan si están activados, para poder analizar el residuo.
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
- **Campos opcionales que puede rellenar** (todos con columna configurable):
  motivo (`#motivo_ia` por defecto), serie detectada (`#serie_ia`), % de
  confianza 0-100 (`#confianza_ia`). Motivo y confianza se guardan siempre
  que la IA responda algo para ese libro, aunque no llegue al umbral.

---

## 8. Menú del plugin

| Acción | Qué hace |
|---|---|
| Clasificar libros seleccionados / TODA la biblioteca | Lanza la clasificación local (niveles 1-3, §4) |
| Rescatar con IA los no clasificados (selección / biblioteca) | Manda a la IA en la nube solo los `[REVISAR]`/`(sin datos)` |
| Reevaluar con IA la selección (ignora marcas) | Igual, pero manda TODOS los seleccionados aunque ya estén clasificados (`force_all`) |
| Limpiar clasificaciones del plugin (selección / biblioteca) | Quita las tags `Biblioteca:`/`Tema:` del plugin |
| Configurar plugin... | Abre el diálogo de preferencias (`config.py`) |

---

## 9. Configuración (`prefs`)

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

---

## 10. Limitaciones conocidas y decisiones deliberadas

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
  (clasificación local, niveles 1-3) funciona sin internet.
- Sin límite de tamaño de biblioteca conocido, pero bibliotecas muy grandes
  generan muchos `ThreadedJob` en paralelo (uno por chunk); Calibre los
  encola internamente.
