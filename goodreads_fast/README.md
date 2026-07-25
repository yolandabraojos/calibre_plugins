# Goodreads Fast — Plugin para Calibre

Fuente de metadatos de Goodreads para la función **Descargar metadatos** de
Calibre. Basado en el plugin "Goodreads" de Grant Drake, reescrito para
buscar por el endpoint de autocompletado (más rápido y no exige ISBN) y con
un emparejamiento título/autor más estricto para evitar traer el libro
equivocado.

## Qué descarga

Título, autores, identificador Goodreads, ISBN, valoración, sinopsis,
editorial, fecha de publicación, etiquetas, serie, idioma y portada.

## Por qué "Fast"

En vez de depender de una búsqueda por ISBN o de scrapear resultados de
búsqueda completos, consulta el **autocompletado en vivo** de Goodreads
(`goodreads.com/book/auto_complete`), que responde con una lista corta de
candidatos ya bastante afinada. Se lanzan varias variantes de la consulta
(título completo, título sin subtítulo, con cada autor por separado, con
título y autor intercambiados como último recurso...) y en cuanto aparece un
candidato claramente bueno, se corta la búsqueda ahí.

## Cómo elige el libro correcto

Cada candidato se puntúa por similitud de título (con o sin subtítulo,
comparando también solo el fragmento antes/después de ":" o "-", útil cuando
el título de Calibre lleva un prefijo de saga) y por coincidencia de autor.
Un candidato solo se acepta si el título coincide claramente; una coincidencia
de autor por sí sola nunca basta (evita, p. ej., confundir libros de autores
con apellido compartido). Si hay ISBN, se usa para fijar la edición exacta,
pero solo si su propio título/autor también encajan — un ISBN mal asignado no
puede imponerse sobre una búsqueda por título que sí coincide. Se descartan
además bundles, boxsets, guías de lectura, resúmenes y omnibus salvo que el
propio libro buscado sea eso.

Cuando hay varias ediciones del mismo libro, se descargan hasta 3 en paralelo
y se entrega primero la de sinopsis más completa (con portada si la hay),
dejando el resto disponible por si prefieres elegir otra edición a mano.

## Etiquetas enriquecidas

Además de las tags que trae la página del libro, añade etiquetas a partir de
las "shelves" (estanterías) populares de Goodreads, ponderadas por número de
votos, para capturar género/tropo que la ficha oficial no siempre recoge.

## Instalación y uso

1. En Calibre: **Preferencias → Plugins → Cargar plugin desde fichero**.
2. Selecciona `GoodreadsFast.zip` y reinicia Calibre.
3. Ve a **Preferencias → Descarga de metadatos** y activa "Goodreads Fast"
   como fuente (puedes desactivar el "Goodreads" original si lo tenías, para
   no duplicar resultados).
4. Usa la descarga de metadatos habitual de Calibre (icono de la varita o
   `Editar metadatos → Descargar metadatos`); no tiene menú ni configuración
   propios, se integra en el flujo estándar de Calibre.

## Limitaciones conocidas

- Depende de que Goodreads esté accesible y de la estructura actual de su
  página/autocompletado; si Goodreads cambia su web, puede dejar de
  funcionar hasta actualizar el plugin.
- El emparejamiento es deliberadamente estricto con el título: si el título o
  autor en Calibre está muy distorsionado (erratas graves, idioma mezclado),
  puede no encontrar coincidencia en vez de arriesgar un match incorrecto.

## Ficheros

| Fichero | Función |
|---|---|
| `__init__.py` | Definición de la fuente de metadatos (`identify`, búsqueda, ranking de candidatos, portada) |
| `worker.py` | Descarga y parseo de la ficha del libro y de las shelves para las etiquetas enriquecidas |
