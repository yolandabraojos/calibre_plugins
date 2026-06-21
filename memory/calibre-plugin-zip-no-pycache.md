---
name: calibre-plugin-zip-no-pycache
description: Los ZIP de plugin de Calibre no deben incluir __pycache__/.pyc; rompen la carga en silencio.
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 50b0c83b-6571-4a60-8d07-1bab24f786a7
---

Un ZIP de plugin de Calibre NO debe contener `__pycache__/` ni `.pyc`. Si se cuelan, Calibre no carga el plugin y no muestra error ni en `calibre-debug` (fallo silencioso). Pasó en BookClassifier.zip: `py_compile` durante la verificación creó `__pycache__` en la carpeta de extracción y `zip -r .` lo empaquetó.

**Why:** el importador de plugins de Calibre se confunde con los `.pyc` precompilados (magic de otra versión de Python) y aborta sin loguear.

**How to apply:** al verificar con `py_compile`, compila a un cfile temporal (`py_compile.compile(f, cfile='/tmp/_c.pyc', doraise=True)`) para no ensuciar la carpeta; antes de empaquetar, `find . -name __pycache__ -prune -exec rm -rf {} +` y `find . -name '*.pyc' -delete`; y construye con `zip -rq plugin.zip . -x '*__pycache__*' '*.pyc'`. Comprueba el ZIP final: ningún nombre debe contener `__pycache__` ni acabar en `.pyc`. Relacionado con [[cloud-sync-write-corruption]].
