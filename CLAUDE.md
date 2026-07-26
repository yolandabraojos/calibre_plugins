# Proyecto: Calibre Plugins

Repositorio git con los plugins de Calibre de Yolanda Braojos. Ubicacion local
`C:\_Proyectos\calibre_plugins` (movido desde OneDrive el 2026-06-21 para evitar
la corrupcion por sincronizacion en la nube).

## Plugins (cada carpeta con `plugin-import-name-*.txt` es un plugin)

| Carpeta              | Nombre Calibre       | Version | ZIP maestro (en dist/)      |
|----------------------|----------------------|---------|-----------------------------|
| book_classifier      | Book Classifier      | 3.4.1   | dist/BookClassifier.zip     |
| ebook_comparator     | Ebook Comparator     | 2.9.0   | dist/EbookComparator.zip    |
| fix_metadata         | Fix Metadata         | 1.7.4   | dist/FixMetadata.zip        |
| extract_metadata     | Extract Metadata     | 1.3.2   | dist/ExtractMetadata.zip    |
| all_libraries_stats  | All Libraries Stats  | 1.0.5   | dist/AllLibrariesStats.zip  |
| goodreads_fast       | Goodreads Fast       | 1.6.0   | dist/GoodreadsFast.zip      |

La version es la fuente de verdad en el `__init__.py` de cada plugin
(`version = (X, Y, Z)`). El generador lee de ahi nombre y version.

## Herramienta fuera de Calibre: duplicados 100 %

`ebook_comparator/dedupe_cli.py` (lanzador `dedupe.cmd`) busca duplicados
exactos sin la interfaz de Calibre, en UNA o MUCHAS bibliotecas. Agrupa por
`comparator.book_fingerprint` (O(n): una extraccion por libro) en vez de
comparar pares, asi que tambien encuentra copias cuyo titulo y autor no se
parecen en nada, y copias repartidas entre bibliotecas distintas.

Flujo en DOS FASES, para no repetir la parte lenta:

1. `dedupe.cmd --root "D:\Bibliotecas"` -- escaneo. Descubre todas las carpetas
   con `metadata.db` bajo la raiz (sin bajar dentro de una biblioteca ya
   encontrada). Es solo lectura, asi que admite Calibre abierto. Escribe un
   informe HTML y un plan `.plan.json`.
2. `dedupe.cmd --apply "...plan.json"` -- borrado, con Calibre cerrado. Segundos.

- Lee `metadata.db` con sqlite3 en `mode=ro`; **nunca** escribe en la base de datos.
- El borrado lo ejecuta Calibre (`calibredb remove`, sin `--permanent`, o
  `api.remove_books` bajo `calibre-debug`), respalda `metadata.db` de cada
  biblioteca antes y aborta si detecta Calibre abierto (`--force-running` lo salta).
- `--apply` **valida el plan** antes de borrar: si un libro cambio de id, titulo,
  ruta, tamano o mtime desde el escaneo, esa entrada se rechaza. Calibre reutiliza
  los ids liberados, asi que sin esto un plan viejo podria borrar otro libro.
- El id de Calibre solo es unico DENTRO de su biblioteca: internamente todo se
  indexa por `uid` = `"<indice de biblioteca>:<id>"`, y el informe da una busqueda
  `id:...` por biblioteca.
- `--prefer-library` fuerza en que biblioteca se conserva la copia; `--skip-cross`
  informa de los duplicados entre bibliotecas sin borrarlos.
- No borra una copia con formatos ausentes en la conservada (p. ej. un PDF extra).

### Criterio de que copia se conserva (UNICO, compartido)

`extractor.epub_provenance()` decide el origen de un EPUB (editorial / calibre /
desconocido) por las marcas del contenedor: jacket y `calibre:timestamp` para las
conversiones; `encryption.xml`, tipografias incrustadas, ISBN y `dc:publisher`
para las ediciones editoriales. Los AZW3 devuelven siempre `desconocido` a
proposito: hay que convertirlos con Calibre para leerlos, asi que la deteccion no
diria nada del fichero original.

Orden de preferencia (menor gana), el MISMO en `dedupe_cli.py --keep plugin` y en
`ui.PairReviewDialog._keep_key`:

1. Biblioteca preferida (`--prefer-library`, solo CLI).
2. EPUB antes que AZW3.
3. Editorial antes que conversion de Calibre.
4. Fichero mas GRANDE.
5. Con portada, y por ultimo id (resultado estable).

Antes de v2.9.0 el plugin **se contradecia**: la regla principal conservaba el
fichero grande, la red de seguridad `_quality` conservaba el pequeno, y el
docstring decia lo contrario del codigo. Las tres cosas usan ya `_keep_key`.
- **Cache de huellas** en `dedupe_out/fingerprint_cache.json`, por
  `(ruta, tamano, mtime)`. Se guarda cada 100 libros y tambien al hacer Ctrl-C,
  asi que un escaneo interrumpido se reanuda repitiendo el mismo comando. Se
  invalida sola si cambia el codigo de `extractor.py` o `comparator.py` (guarda
  su hash): huellas de motores distintos no son comparables. `--no-cache` /
  `--clear-cache`.
- Los informes y planes van a `dedupe_out/` (en `.gitignore`), **nunca** a la
  carpeta del plugin: `build_plugins.py` empaqueta todo lo que hay ahi y un
  informe suelto acabo dentro del ZIP (ya excluye `duplicados_*` y `*.plan.json`).
- `--epub-only` omite los AZW3, que hay que convertir con `ebook-convert` y son
  el coste dominante del escaneo. El resumen de tiempos por formato lo cuantifica.

## Regla de oro: NO usar Write/Edit sobre esta carpeta

Esta carpeta esta montada a traves del cliente de archivos. Las herramientas
Write/Edit **corrompen** los ficheros (truncado / bytes nulos por la hidratacion
bajo demanda). Comprobado: una edicion trunco `build_plugins.py` a mitad de linea.

Para ficheros de codigo o texto:
- Escribe con **bash** (heredoc `cat > fichero <<'EOF'` o redireccion) directamente
  sobre la ruta montada, o crea en local y copia con `cp`.
- El borrado por bash requiere permiso (`rm` da "Operation not permitted" hasta
  que se concede); si falla, solicitar permiso de borrado de la carpeta.
- **Verifica siempre** tras escribir: contar bytes nulos y compilar/parsear.

El ZIP del entregable es la copia maestra fiable (los binarios no se corrompen):
instala/comparte siempre desde un ZIP que el verificador marque ÍNTEGRO.

## Estructura

- La **raiz** contiene solo las fuentes (carpetas de plugin) y las herramientas
  (`build_plugins.py`, `verificar_plugin.py`, `build.cmd`, `verify.cmd`, `CLAUDE.md`).
- Todos los **artefactos** (ZIP) se generan en `dist/` y estan en `.gitignore`
  (no se versionan).

## Generar los ZIP

```
python build_plugins.py            # construye + verifica TODOS los plugins
python build_plugins.py fix_metadata   # solo uno
python build_plugins.py --verify   # solo verifica los ZIP de dist/
```
En Windows: doble clic en `build.cmd` (todos) o `verify.cmd` (solo verificar).

El generador:
- Auto-descubre plugins por el marcador `plugin-import-name-*.txt`.
- Empaqueta los ficheros en la RAIZ del ZIP (como exige Calibre).
- **Excluye** `__pycache__/`, `*.pyc`, `.build/`, `*.bak*` y basura del SO.
  Incluir `__pycache__`/`.pyc` rompe la carga del plugin en Calibre en silencio.
- Escribe en `dist/`: el maestro `dist/<NombrePlugin>.zip` (para instalar) y una
  copia versionada `dist/<NombrePlugin>-vX.Y.Z.zip`.
- Verifica cada ZIP: sin bytes nulos en texto, los `.py` compilan, JSON valido.

## Verificacion

- `verificar_plugin.py` revisa las carpetas de plugin Y los ZIP de `dist/`.
- `build_plugins.py` verifica los ZIP recien generados.
- Un cambio se da por bueno solo si el resultado es **ÍNTEGRO**.

## Flujo para actualizar un plugin

1. Editar las fuentes del plugin con **bash** (nunca Write/Edit).
2. Subir la version en `__init__.py` si procede.
3. `python build_plugins.py <plugin>` y confirmar ÍNTEGRO.
4. Instalar en Calibre desde `dist/<NombrePlugin>.zip`.
5. `git add/commit` cuando este validado (los ZIP de dist/ no se versionan).

## Notas

- Copia de respaldo del trabajo previo: carpeta OneDrive
  `Documentos\Claude\Projects\Calibre - Clasificacion` (intacta; datos de
  entrenamiento, xlsx de pesos, csv, biblioteca de pruebas).
- Memoria del proyecto en `memory/` (indice en `memory/MEMORY.md`).
