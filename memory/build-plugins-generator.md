---
name: build-plugins-generator
description: build_plugins.py genera y verifica los ZIP maestros en dist/; excluye __pycache__/.pyc; build.cmd/verify.cmd en Windows.
metadata:
  node_type: reference
---

`build_plugins.py` (raiz del repo `C:\_Proyectos\calibre_plugins`) genera y verifica
los ZIP de todos los plugins. Multiplataforma (solo Python 3).

- `python build_plugins.py` -> construye + verifica TODOS.
- `python build_plugins.py <carpeta>` -> solo ese/esos plugins.
- `python build_plugins.py --verify` -> solo verifica los ZIP de dist/.
- Windows: `build.cmd` (todos) y `verify.cmd` (solo verificar).

Comportamiento:
- Auto-descubre plugins por el marcador `plugin-import-name-*.txt`.
- Lee nombre+version del `__init__.py`. TODOS los artefactos van a `dist/`
  (la raiz queda solo con fuentes): el maestro `dist/<NombreCamel>.zip`
  (ej. 'Book Classifier' -> dist/BookClassifier.zip) para instalar, y una copia
  versionada `dist/<Nombre>-vX.Y.Z.zip`. `dist/` esta en .gitignore.
- Empaqueta los ficheros en la RAIZ del ZIP (como exige Calibre).
- EXCLUYE `__pycache__/`, `*.pyc`, `.build/`, `*.bak*` y basura del SO
  (ver [[calibre-plugin-zip-no-pycache]]).
- Verifica cada ZIP: bytes nulos SOLO en ficheros de texto (los .png los tienen de
  forma legitima), los `.py` compilan, JSON valido, ZIP integro.

`verificar_plugin.py` (heredado) hace una verificacion equivalente sobre las CARPETAS
de plugin y los ZIP de `dist/`. Un cambio es valido solo si el resultado es INTEGRO.
