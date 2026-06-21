# -*- coding: utf-8 -*-
"""
Verificador de integridad de los plugins de Calibre del proyecto.

Comprueba, para CADA plugin, que sus ficheros .py no tienen bytes nulos
(corrupción típica de la sincronización en la nube / montaje), que compilan,
y que sus JSON son válidos.

Auto-descubre los plugins: cualquier subcarpeta que contenga un fichero marcador
`plugin-import-name-*.txt` (el que usa Calibre) se trata como plugin.

También verifica los *.zip de plugin que haya en `dist/` (los genera
build_plugins.py), descomprimiéndolos en un temporal y revisando su contenido.

Uso:  python verificar_plugin.py
"""
import os
import sys
import json
import zipfile
import py_compile
import tempfile

BASE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(BASE, 'dist')

ok = True


def _count_nulls(data):
    return data.count(b'\x00')


def check_py(path, label):
    """Comprueba un .py: sin bytes nulos y que compila."""
    global ok
    try:
        with open(path, 'rb') as f:
            data = f.read()
    except Exception as e:
        print('  [FALTA] {}: {}'.format(label, e)); ok = False; return
    nulls = _count_nulls(data)
    if nulls:
        print('  [CORRUPTO] {}: {} bytes nulos'.format(label, nulls)); ok = False; return
    try:
        tmp_pyc = os.path.join(tempfile.gettempdir(), 'verif_tmp.pyc')
        py_compile.compile(path, cfile=tmp_pyc, doraise=True)
        print('  [OK] {}'.format(label))
    except Exception as e:
        print('  [ERROR SINTAXIS] {}: {}'.format(label, e)); ok = False


def check_json(path, label):
    """Comprueba un .json: sin bytes nulos y JSON válido."""
    global ok
    try:
        with open(path, 'rb') as f:
            if _count_nulls(f.read()):
                print('  [CORRUPTO] {}: bytes nulos'.format(label)); ok = False; return
        with open(path, 'r', encoding='utf-8') as f:
            json.load(f)
        print('  [OK] {}'.format(label))
    except Exception as e:
        print('  [ERROR] {}: {}'.format(label, e)); ok = False


def is_plugin_dir(path):
    if not os.path.isdir(path):
        return False
    for name in os.listdir(path):
        if name.startswith('plugin-import-name-') and name.endswith('.txt'):
            return True
    return False


def check_dir(plugin_dir):
    py_files = sorted(f for f in os.listdir(plugin_dir) if f.endswith('.py'))
    json_files = sorted(f for f in os.listdir(plugin_dir) if f.endswith('.json'))
    if not py_files and not json_files:
        print('  (sin ficheros .py / .json)')
        return
    for f in py_files:
        check_py(os.path.join(plugin_dir, f), f)
    for f in json_files:
        check_json(os.path.join(plugin_dir, f), f)


def zip_is_plugin(zip_path):
    try:
        with zipfile.ZipFile(zip_path) as z:
            for n in z.namelist():
                base = os.path.basename(n)
                if base.startswith('plugin-import-name-') and base.endswith('.txt'):
                    return True
    except Exception:
        return False
    return False


def check_zip(zip_path):
    global ok
    try:
        with zipfile.ZipFile(zip_path) as z:
            bad = z.testzip()
            if bad:
                print('  [CORRUPTO] entrada dañada:', bad); ok = False
            with tempfile.TemporaryDirectory() as tmp:
                z.extractall(tmp)
                py_found = False
                for root, _dirs, files in os.walk(tmp):
                    for f in sorted(files):
                        rel = os.path.relpath(os.path.join(root, f), tmp)
                        if f.endswith('.py'):
                            py_found = True
                            check_py(os.path.join(root, f), 'zip/' + rel)
                        elif f.endswith('.json'):
                            check_json(os.path.join(root, f), 'zip/' + rel)
                if not py_found:
                    print('  [AVISO] el zip no contiene ningún .py'); ok = False
    except Exception as e:
        print('  [ERROR] no se pudo abrir el zip:', e); ok = False


# --------------------------------------------------------------------------- #
#  Recorrido principal
# --------------------------------------------------------------------------- #
print('=== CARPETAS DE PLUGIN ===')
plugin_dirs = sorted(
    d for d in os.listdir(BASE)
    if is_plugin_dir(os.path.join(BASE, d))
)
if plugin_dirs:
    for d in plugin_dirs:
        print('\n-- {}/ --'.format(d))
        check_dir(os.path.join(BASE, d))
else:
    print('  (no se encontró ninguna carpeta de plugin)')

print('\n=== ZIPS DE PLUGIN (dist/) ===')
zips = []
if os.path.isdir(DIST):
    zips = sorted(
        f for f in os.listdir(DIST)
        if f.lower().endswith('.zip') and zip_is_plugin(os.path.join(DIST, f))
    )
if zips:
    for f in zips:
        print('\n-- dist/{} --'.format(f))
        check_zip(os.path.join(DIST, f))
else:
    print('  (no se encontró ningún zip de plugin en dist/; ejecuta build_plugins.py)')

print()
print('RESULTADO:',
      'TODO INTEGRO ✓' if ok
      else 'HAY PROBLEMAS ✗  (reinstala desde un ZIP que de INTEGRO)')
sys.exit(0 if ok else 1)
