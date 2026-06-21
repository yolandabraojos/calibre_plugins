# Proyecto: Calibre Plugins

Repositorio git con los plugins de Calibre de Yolanda Braojos. Ubicacion local
`C:\_Proyectos\calibre_plugins` (movido desde OneDrive el 2026-06-21 para evitar
la corrupcion por sincronizacion en la nube).

## Plugins (cada carpeta con `plugin-import-name-*.txt` es un plugin)

| Carpeta              | Nombre Calibre       | Version | ZIP maestro            |
|----------------------|----------------------|---------|------------------------|
| book_classifier      | Book Classifier      | 3.0.0   | BookClassifier.zip     |
| ebook_comparator     | Ebook Comparator     | 2.6.2   | EbookComparator.zip    |
| fix_metadata         | Fix Metadata         | 1.3.3   | FixMetadata.zip        |
| extract_metadata     | Extract Metadata     | 1.3.2   | ExtractMetadata.zip    |
| all_libraries_stats  | All Libraries Stats  | 1.0.5   | AllLibrariesStats.zip  |

La version es la fuente de verdad en el `__init__.py` de cada plugin
(`version = (X, Y, Z)`). El generador lee de ahi nombre y version.

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

## Generar los ZIP

```
python build_plugins.py            # construye + verifica TODOS los plugins
python build_plugins.py fix_metadata   # solo uno
python build_plugins.py --verify   # solo verifica los ZIP existentes
```
En Windows: doble clic en `build.cmd` (todos) o `verify.cmd` (solo verificar).

El generador:
- Auto-descubre plugins por el marcador `plugin-import-name-*.txt`.
- Empaqueta los ficheros en la RAIZ del ZIP (como exige Calibre).
- **Excluye** `__pycache__/`, `*.pyc`, `.build/`, `*.bak*` y basura del SO.
  Incluir `__pycache__`/`.pyc` rompe la carga del plugin en Calibre en silencio.
- Escribe el maestro en la raiz (`<NombrePlugin>.zip`) y una copia versionada
  en `dist/<NombrePlugin>-vX.Y.Z.zip`.
- Verifica cada ZIP: sin bytes nulos en texto, los `.py` compilan, JSON valido.

## Verificacion

- `verificar_plugin.py` revisa las carpetas de plugin Y los ZIP de la raiz.
- `build_plugins.py` verifica los ZIP recien generados.
- Un cambio se da por bueno solo si el resultado es **ÍNTEGRO**.

## Flujo para actualizar un plugin

1. Editar las fuentes del plugin con **bash** (nunca Write/Edit).
2. Subir la version en `__init__.py` si procede.
3. `python build_plugins.py <plugin>` y confirmar ÍNTEGRO.
4. Instalar en Calibre desde el ZIP maestro de la raiz.
5. `git add/commit` cuando este validado.

## Notas

- Copia de respaldo del trabajo previo: carpeta OneDrive
  `Documentos\Claude\Projects\Calibre - Clasificacion` (intacta; datos de
  entrenamiento, xlsx de pesos, csv, biblioteca de pruebas).
- Memoria del proyecto en `memory/` (indice en `memory/MEMORY.md`).
