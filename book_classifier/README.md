# Book Classifier (IA local) — Plugin para Calibre

Clasifica tu biblioteca con un **modelo de IA entrenado con tus propios libros**. No
usa internet ni dependencias externas: el modelo viaja como pesos en un JSON y se
ejecuta en el Python de Calibre. Trabaja en **dos ejes**:

- **Eje 1 — Librería** *(excluyente)*: sugiere UNA librería por libro, con un nivel de
  confianza. Si la confianza es baja, marca `Biblioteca: (revisar)` en vez de arriesgar.
- **Eje 2 — Tema** *(multi-etiqueta)*: añade tags de tono/tropo (`Tema: Vampiros`,
  `Tema: Mafia`, `Tema: Slow burn`…) para buscar por lo que te apetece leer.

Se ejecuta como **trabajo en segundo plano** con barra de progreso y cancelación.

## Librerías que predice

`Romance contemporáneo` · `Romance histórico` · `Romantasy / Paranormal` ·
`Fantasía & Sci-Fi` · `Misterio·Thriller·Terror` · `Ficción general`

## Cómo funciona

Para cada libro concatena los campos elegidos (por defecto título + sinopsis + tags),
y el modelo (regresión logística sobre TF-IDF) predice la librería. En paralelo, unas
reglas de palabras clave bilingües (`mood_rules.json`) detectan los tropos.

Acierto medido sobre los libros ya clasificados a mano: **~89%** cuando el libro tiene
tags ricos, **~70%** solo con título + sinopsis. Los libros sin sinopsis se marcan
`(sin datos)`.

## Instalación

1. En Calibre: **Preferencias → Plugins → Cargar plugin desde fichero**.
2. Selecciona `BookClassifier.zip` y reinicia Calibre.

## Uso

| Acción | Dónde |
|---|---|
| Clasificar selección | Clic en el icono, o menú del plugin |
| Clasificar toda la biblioteca | Menú del plugin |
| Quitar etiquetas del plugin | Menú → *Limpiar clasificaciones* |
| Ajustes (campos, umbral, destino) | Menú → *Configurar plugin* |

Por defecto todo se escribe en `tags` con los prefijos `Biblioteca:` y `Tema:`, así se
agrupan solos en el navegador de etiquetas. Puedes mandar la librería a una columna
propia (p. ej. `#libreria`) desde los ajustes.

## Cómo dividir en varias bibliotecas de Calibre

1. Clasifica toda la biblioteca.
2. En la barra de búsqueda: `tags:"Biblioteca: Romance contemporáneo"`.
3. Selecciona todo → clic derecho → *Copiar a biblioteca* (o *Mover a biblioteca*).
4. Repite por cada librería. Los `Biblioteca: (revisar)` quedan para mirar a mano.

## Ficheros

| Fichero | Función |
|---|---|
| `__init__.py` | Registro del plugin |
| `action.py` | Menú, diálogos y lanzamiento del trabajo |
| `ml_jobs.py` | Worker en segundo plano (lee, clasifica, escribe) |
| `ml_classifier.py` | Motor IA en Python puro + reglas de tema |
| `config.py` | Ajustes |
| `model_weights.json` | Modelo entrenado (vocabulario + pesos por librería) |
| `mood_rules.json` | Reglas de palabras clave de los tags de tema |

## Reentrenar el modelo

El modelo se entrena fuera de Calibre con tus CSV etiquetados y se exporta a
`model_weights.json`. Para mejorarlo, reexporta ese fichero y sustitúyelo (en el plugin
o en la carpeta de configuración de Calibre). Las reglas de tema (`mood_rules.json`)
se editan a mano sin tocar código.
