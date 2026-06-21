# -*- coding: utf-8 -*-
"""
Generador de ZIPs de los plugins de Calibre de este proyecto.

Multiplataforma (solo necesita Python 3). Para CADA carpeta que sea un plugin
(contiene un marcador `plugin-import-name-*.txt`):

  1. Lee `name` y `version` de su __init__.py.
  2. Empaqueta sus ficheros en la RAIZ de un ZIP (como exige Calibre),
     EXCLUYENDO __pycache__, *.pyc, .build/, *.bak* y basura del SO.
  3. Escribe el ZIP maestro en la raiz del repo  ->  <NombrePlugin>.zip
     y una copia versionada en  dist/<NombrePlugin>-vX.Y.Z.zip
  4. Verifica el ZIP recien creado: sin bytes nulos en ficheros de texto,
     compila los .py, JSON valido y el propio ZIP integro.

Uso:
    python build_plugins.py            # construye y verifica todos
    python build_plugins.py book_classifier ebook_comparator   # solo esos
    python build_plugins.py --verify   # NO construye, solo verifica los ZIP

Codigo de salida 0 si TODO queda integro, 1 si hay algun problema.
"""
import os
import re
import sys
import json
import zipfile
import tempfile
import py_compile

BASE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(BASE, 'dist')

EXCLUDE_DIRS  = {'__pycache__', '.build', '.git', 'dist'}
EXCLUDE_EXTS  = {'.pyc', '.pyo'}
EXCLUDE_NAMES = {'.DS_Store', 'Thumbs.db', 'desktop.ini'}
TEXT_EXTS     = ('.py', '.json', '.txt', '.md', '.csv', '.cfg', '.ini', '.pot')


def log(msg=''):
    print(msg, flush=True)


def is_plugin_dir(path):
    if not os.path.isdir(path):
        return False
    return any(n.startswith('plugin-import-name-') and n.endswith('.txt')
               for n in os.listdir(path))


def read_meta(plugin_dir):
    """Devuelve (name, version_str) leidos del __init__.py del plugin."""
    init = os.path.join(plugin_dir, '__init__.py')
    name, version = None, None
    try:
        with open(init, 'r', encoding='utf-8') as f:
            src = f.read()
    except Exception:
        src = ''
    m = re.search(r"""name\s*=\s*['"]([^'"]+)['"]""", src)
    if m:
        name = m.group(1)
    m = re.search(r"version\s*=\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", src)
    if m:
        version = '.'.join(m.groups())
    if not name:
        name = os.path.basename(plugin_dir)
    if not version:
        version = '0.0.0'
    return name, version


def zip_basename(name):
    """'Book Classifier' -> 'BookClassifier'."""
    return ''.join(p[:1].upper() + p[1:] for p in re.split(r'\s+', name.strip()) if p)


def included_files(plugin_dir):
    """Itera (ruta_absoluta, arcname) de lo que SI va al ZIP."""
    for root, dirs, files in os.walk(plugin_dir):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for f in sorted(files):
            if f in EXCLUDE_NAMES:
                continue
            if os.path.splitext(f)[1].lower() in EXCLUDE_EXTS:
                continue
            if f.endswith('.bak') or '.bak.' in f:
                continue
            full = os.path.join(root, f)
            arc = os.path.relpath(full, plugin_dir).replace(os.sep, '/')
            yield full, arc


def build_zip(plugin_dir):
    name, version = read_meta(plugin_dir)
    base = zip_basename(name)
    master = os.path.join(BASE, base + '.zip')
    os.makedirs(DIST, exist_ok=True)
    versioned = os.path.join(DIST, '{}-v{}.zip'.format(base, version))

    files = list(included_files(plugin_dir))
    for target in (master, versioned):
        tmp = target + '.tmp'
        with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as z:
            for full, arc in files:
                z.write(full, arc)
        if os.path.exists(target):
            os.remove(target)
        os.replace(tmp, target)
    log('  [BUILD] {} v{}  ->  {}.zip  ({} ficheros)'.format(
        name, version, base, len(files)))
    return master


def verify_zip(zip_path):
    """True si el ZIP es integro."""
    ok = True
    label = os.path.basename(zip_path)
    try:
        with zipfile.ZipFile(zip_path) as z:
            if z.testzip() is not None:
                log('  [CORRUPTO] {}: entrada danada'.format(label))
                return False
            names = z.namelist()
            if not any(os.path.basename(n).startswith('plugin-import-name-')
                       for n in names):
                log('  [AVISO] {}: sin marcador plugin-import-name'.format(label))
                ok = False
            if not any(n.endswith('.py') for n in names):
                log('  [AVISO] {}: sin ficheros .py'.format(label))
                ok = False
            with tempfile.TemporaryDirectory() as tmp:
                z.extractall(tmp)
                for root, _d, files in os.walk(tmp):
                    for f in files:
                        p = os.path.join(root, f)
                        with open(p, 'rb') as fh:
                            data = fh.read()
                        if f.lower().endswith(TEXT_EXTS) and b'\x00' in data:
                            log('  [CORRUPTO] {}/{}: bytes nulos'.format(label, f))
                            ok = False
                        if f.endswith('.py'):
                            try:
                                py_compile.compile(
                                    p,
                                    cfile=os.path.join(tempfile.gettempdir(), 'b.pyc'),
                                    doraise=True)
                            except Exception as e:
                                log('  [SINTAXIS] {}/{}: {}'.format(label, f, e))
                                ok = False
                        elif f.endswith('.json'):
                            try:
                                json.loads(data.decode('utf-8'))
                            except Exception as e:
                                log('  [JSON] {}/{}: {}'.format(label, f, e))
                                ok = False
    except Exception as e:
        log('  [ERROR] no se pudo abrir {}: {}'.format(label, e))
        return False
    if ok:
        log('  [OK] {}'.format(label))
    return ok


def discover(selected):
    found = []
    for d in sorted(os.listdir(BASE)):
        full = os.path.join(BASE, d)
        if is_plugin_dir(full) and (not selected or d in selected):
            found.append(full)
    return found


def main(argv):
    verify_only = '--verify' in argv
    selected = [a for a in argv if not a.startswith('--')]
    plugins = discover(selected)
    if not plugins:
        log('No se encontro ningun plugin.')
        return 1

    ok = True
    if not verify_only:
        log('=== GENERANDO ZIPS ===')
        zips = [build_zip(p) for p in plugins]
    else:
        zips = []
        for p in plugins:
            name, _ = read_meta(p)
            z = os.path.join(BASE, zip_basename(name) + '.zip')
            if os.path.exists(z):
                zips.append(z)

    log('')
    log('=== VERIFICANDO ZIPS ===')
    for z in zips:
        if not verify_zip(z):
            ok = False

    log('')
    log('RESULTADO: ' + ('TODO INTEGRO' if ok else 'HAY PROBLEMAS'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
