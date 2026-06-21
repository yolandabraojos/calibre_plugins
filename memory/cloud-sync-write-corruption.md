---
name: cloud-sync-write-corruption
description: Las herramientas Write/Edit corrompen ficheros de texto en carpetas sincronizadas y en el montaje cowork; escribir con bash y verificar.
metadata:
  node_type: memory
  type: feedback
---

Las herramientas **Write y Edit corrompen ficheros de texto/codigo** cuando la
carpeta de trabajo esta sincronizada en la nube (OneDrive, Dropbox, Google Drive,
iCloud): insertan bytes nulos y truncan contenido por la hidratacion bajo demanda.
Confirmado repetidamente en el proyecto de Calibre de Yolanda.

**AMPLIACION (2026-06-21):** ocurre tambien en la carpeta LOCAL montada por cowork
`C:\_Proyectos\calibre_plugins`. Una sola edicion con Edit trunco `build_plugins.py`
a mitad de linea (de 206 a 190 lineas, `SyntaxError: unterminated string`). Es decir,
NO basta con sacar el proyecto de OneDrive: el problema es el montaje, asi que en
estas carpetas NUNCA usar Write/Edit, sea local o nube.

**How to apply:**
- Para fuentes/texto, escribir con **bash**: heredoc (`cat > f <<'EOF' ... EOF`) o
  redireccion sobre la ruta montada; o crear en el sandbox y `cp`.
- El borrado por bash da "Operation not permitted" hasta concederlo: usar el permiso
  de borrado de la carpeta (allow_cowork_file_delete) y reintentar `rm`.
- Verificar SIEMPRE tras escribir: contar bytes nulos
  (`python -c "print(open('f','rb').read().count(b'\x00'))"`) y compilar/parsear
  (`python -m py_compile`, `json.load`). Reescribir si esta corrupto.
- El **ZIP** del entregable es la copia maestra fiable (los binarios no se corrompen):
  instalar/compartir desde un ZIP que el verificador marque INTEGRO.
- Relacionado: [[calibre-plugin-zip-no-pycache]], [[calibre-plugins-repo-local]],
  [[build-plugins-generator]].
