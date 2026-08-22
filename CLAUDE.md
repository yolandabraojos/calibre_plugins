# Proyecto: Calibre Plugins

Repositorio git con los plugins de Calibre de Yolanda Braojos. Ubicacion local
`C:\_Proyectos\calibre_plugins` (movido desde OneDrive el 2026-06-21 para evitar
la corrupcion por sincronizacion en la nube).

## Plugins (cada carpeta con `plugin-import-name-*.txt` es un plugin)

| Carpeta              | Nombre Calibre       | Version | ZIP maestro (en dist/)      |
|----------------------|----------------------|---------|-----------------------------|
| book_classifier      | Book Classifier      | 3.20.0  | dist/BookClassifier.zip     |
| ebook_comparator     | Ebook Comparator     | 2.9.5   | dist/EbookComparator.zip    |
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
- **Antes de borrar exporta una copia** con `calibredb export` a
  `dedupe_out/exportadas_<fecha>/` (ficheros + portada + OPF). Si la exportacion
  falla, NO se borra nada de esa biblioteca. `--no-export` lo desactiva.
  Antes de borrar se comprueba que la copia esta COMPLETA (un `metadata.opf` por
  libro); si faltan, no se borra nada de esa biblioteca.
- **La papelera de Calibre NO es una red de seguridad fiable.** Comprobado en la
  biblioteca real de Yolanda: tras borrar 1909 libros con `calibredb remove` sin
  `--permanent`, "Restaurar libros borrados recientemente" aparecio VACIO
  (0 libros, 0 formatos). Ademas su ajuste "Permanently delete after" estaba en
  "on close", que vacia la papelera al cerrar Calibre. Tratar el borrado como
  DEFINITIVO: lo unico que recupera los ficheros es la carpeta exportada, y lo
  unico que recupera la base de datos es el `metadata.db.bak-*`.
- `--apply` **valida el plan** antes de borrar: si un libro cambio de id, titulo,
  ruta, tamano o mtime desde el escaneo, esa entrada se rechaza. Calibre reutiliza
  los ids liberados, asi que sin esto un plan viejo podria borrar otro libro.
- El id de Calibre solo es unico DENTRO de su biblioteca: internamente todo se
  indexa por `uid` = `"<indice de biblioteca>:<id>"`, y el informe da una busqueda
  `id:...` por biblioteca.
- `--prefer-library` fuerza en que biblioteca se conserva la copia; `--skip-cross`
  informa de los duplicados entre bibliotecas sin borrarlos.
- De cada registro solo se COMPARA un fichero (EPUB si lo hay, si no AZW3), pero
  antes de borrar se verifican los formatos SECUNDARIOS de los candidatos: si el
  AZW3 de un registro tiene otra huella que el grupo, ese registro no se borra
  (podria ser otro libro colado bajo el mismo id). Solo se verifican los
  candidatos a borrar, no toda la biblioteca. `--no-verify-formats` lo salta.
- No borra una copia con formatos NO COMPARADOS ausentes en la conservada
  (p. ej. un PDF o un MOBI extra). EPUB y AZW3 **no** protegen: son los que se
  comparan y el criterio ya decide entre ellos, asi que proteger un AZW3 "por
  ser el unico AZW3" impediria borrarlo nunca.

### Convertir a EPUB los registros que solo tienen AZW3

`dedupe.cmd --convert-azw3 --root "..."` es un modo APARTE que **escribe** en la
biblioteca (exige Calibre cerrado); el escaneo se lanza despues.

- Alcance: registros con AZW3 y **sin** EPUB. Los que ya tienen ambos no se tocan.
- `ebook-convert ... --flow-size 0 --dont-split-on-page-breaks` (evita los
  fragmentos `partNNNN_split_00M.html`) y luego `calibredb add_format` al MISMO id.
- **El AZW3 se conserva**: la operacion es reversible borrando el formato EPUB.
  `add_format` es aditivo, asi que no hace falta exportar antes.
- **El cuello de botella era `calibredb add_format`**, no `ebook-convert`: cada
  llamada arranca Calibre entero (~2 s), y en serie son mas de una hora para 1600
  libros. Medido: 0,29 libros/s con `--jobs 20` y 0,28 con `--jobs 6`, identico,
  porque el paralelismo de la conversion no cambiaba nada. Ahora los EPUB se
  acumulan (`--batch`, 100 por defecto) y se anaden de golpe con UNA invocacion de
  `calibre-debug -e` que usa `db.new_api.add_format`. Si no hay `calibre-debug`,
  cae a `calibredb` de uno en uno y avisa.
- Tuberia continua, no por lotes: con lotes, mientras se anadian los formatos no
  se convertia nada. El resumen imprime que porcentaje del tiempo se fue en anadir.
- Ctrl-C: mata las conversiones en marcha (`taskkill /T` en Windows, con barridos
  sucesivos para cerrar la carrera con los hilos que estaban lanzando), **anade lo
  ya convertido** antes de salir y borra el temporal con `ignore_errors` (en
  Windows no se puede eliminar un fichero en uso). Repetir el comando reanuda.
- Respalda `metadata.db` de cada biblioteca. Un fallo (tipico: DRM) no aborta la
  tanda: se recoge en `dedupe_out/conversion_azw3_<fecha>.txt` con la linea `id:`
  de los convertidos. `--ids 1,2,3` limita el alcance para probar.
- Motivo: los AZW3 son el coste dominante del escaneo (se reconvierten en cada
  pasada) y su huella sale de una conversion al vuelo, que puede no coincidir con
  la de una copia EPUB sana del mismo libro.

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

## Herramienta fuera de Calibre: cambiar el TIPO de una columna

`scripts/convert_column.py` (lanzador `convertir_columna.cmd`) convierte una
columna personalizada de un tipo a otro CONSERVANDO los valores. Motivo: el
`#subtitle` de Yolanda se creo como *Long text, like comments* y el dialogo de
revision de Fix Metadata lo pinta como un editor enorme; se quiere *Text,
column shown in the Tag browser*. Calibre **no permite cambiar el tipo** de una
columna existente, ni por la interfaz ni por la API.

    convertir_columna.cmd --list-libraries              bibliotecas conocidas
    convertir_columna.cmd --list                        ver columnas y tipos
    convertir_columna.cmd --column subtitle --dry-run   ensayo, no toca nada
    convertir_columna.cmd --column subtitle             hacerlo
    convertir_columna.cmd --column subtitle --to comments   vuelta atras
    convertir_columna.cmd --restore "columnas_out\subtitle_XXX.json"

- La biblioteca se da por **NOMBRE** o por ruta: `-l "Mi Biblioteca"`. Los
  nombres salen de `library_usage_stats` en el `gui.json` de Calibre (lo que
  llena "Cambiar biblioteca") mas la abierta ahora, y de `--root` si se pasa.
  La busqueda es exacta -> empieza por -> contiene, y **aborta si hay empate**
  en vez de elegir. `--all-libraries` lo aplica a todas.
- Es **generico**: vale para cualquier columna de un solo valor (`#serie_gen`,
  `#world`...). Aborta si la columna es de valores multiples.
- Secuencia: exporta a JSON -> respalda `metadata.db` -> borra la columna ->
  la recrea con el tipo pedido (mismo nombre visible) -> reescribe los valores
  -> **verifica** reabriendo la biblioteca y comparando valor a valor.
- **ESCRIBE en la biblioteca**: exige la INTERFAZ de Calibre cerrada
  (`--force-running` lo salta). Solo bloquea `calibre.exe`: los *calibre worker
  process* (`calibre-parallel.exe`) que quedan sueltos tras cerrar Calibre no
  tienen la biblioteca abierta, asi que solo se avisa de ellos. Contarlos como
  "Calibre abierto" impedia trabajar sin motivo.
- Las rutas se limpian de espacios y comillas sobrantes: `--root " C:\Libros"`
  (con el espacio dentro de las comillas, facil en PowerShell) dejaba de ser
  absoluta y se resolvia contra la carpeta actual.
- `--root` sin `--library`: si bajo la raiz hay UNA biblioteca, se usa; si hay
  varias, las lista y pide elegir con `-l`.
- Corre bajo `calibre-debug -e` porque necesita la API (`create_custom_column` /
  `delete_custom_column`, que se buscan en `new_api` y, si no estan, en su
  `backend`). Entre paso y paso **reabre la biblioteca**, porque una Cache ya
  abierta no ve la columna recien creada.
- El HTML de la columna comments se pasa a texto plano (`<br>` y fin de parrafo
  -> separador `--sep`, por defecto un espacio; entidades desescapadas). **No
  trunca**: informa de los valores de mas de 200 caracteres, que suelen ser
  sinopsis coladas, pero los conserva enteros.
- **Una columna `text` NO distingue mayusculas** (su tabla es
  `UNIQUE ... COLLATE NOCASE`, como las etiquetas): 'A Novel', 'A novel' y
  'a Novel' son el MISMO valor: una sola fila a la que APUNTAN todos esos
  libros. Como solo cabe una grafia, la verificacion daba falsos errores.
  Ahora se elige ANTES de escribir la del PRIMER libro que la tenia (por id,
  estable y predecible; antes ganaba la primera escrita, que dependia del orden
  de recorrido) y se fuerza con `rename_items()`,
  porque `set_field()` reutiliza la fila existente sin cambiarle la grafia. La
  verificacion informa de las diferencias de mayusculas sin darlas por error.
- Red de seguridad doble: `columnas_out/<columna>_<fecha>.json` (en
  `.gitignore`) con el valor bruto y el limpio de cada libro, y
  `metadata.db.bak-<fecha>` dentro de la biblioteca. Si la reescritura falla,
  `--restore` reimporta el JSON sin repetir el borrado.

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
