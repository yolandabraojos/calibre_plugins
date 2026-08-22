# -*- coding: utf-8 -*-
"""
Configuración del plugin (clasificación con IA local).
"""

from qt.core import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QCheckBox, QGroupBox, QLineEdit, QScrollArea, QPushButton, QMessageBox,
    QInputDialog
)
from calibre.utils.config import JSONConfig, config_dir

# Campos de los que se extrae el texto a analizar
STANDARD_FIELDS = [
    ('title',    'Título'),
    ('comments', 'Comentarios / Sinopsis'),
    ('tags',     'Etiquetas (tags)'),
    ('series',   'Serie'),
]

# Almacenamiento persistente
prefs = JSONConfig('plugins/book_classifier')
prefs.defaults['source_fields']     = ['title', 'comments', 'tags']
prefs.defaults['ml_use_subtitle']   = True
prefs.defaults['ml_subtitle_field'] = '#subtitle'
prefs.defaults['ml_library_field']  = 'tags'
prefs.defaults['ml_mood_field']     = 'tags'
prefs.defaults['ml_library_prefix'] = 'Biblioteca: '
prefs.defaults['ml_mood_prefix']    = 'Tema: '
prefs.defaults['ml_threshold']      = 0.55
prefs.defaults['ml_write_library']  = True
prefs.defaults['ml_write_moods']    = True
prefs.defaults['ml_overwrite']      = True
# Unificación por serie / universo
prefs.defaults['ml_group_unify']       = True
prefs.defaults['ml_group_unify_moods'] = True
prefs.defaults['ml_universe_field']    = '#universe'
# Consenso por autor (tercer nivel, para los dudosos)
prefs.defaults['ml_author_fallback']  = True
prefs.defaults['ml_author_dominance'] = 0.6
# Rescate con IA en la nube (capa híbrida, opcional)
prefs.defaults['llm_provider']    = 'glm'
prefs.defaults['llm_api_key']     = ''
prefs.defaults['llm_model']       = ''
# URL del servidor. Vacia = la del proveedor elegido. Se rellena para usar
# un servidor compatible con OpenAI que no este en la lista (proveedor
# 'otro'), o para apuntar a otro sitio uno de los conocidos.
prefs.defaults['llm_base_url']    = ''
# Libros por llamada. 20 en vez de 10 desde 3.11.0: la parte FIJA del prompt
# (reglas + mapa de subgeneros + los temas con su descripcion) se paga en CADA
# llamada, asi que doblar el lote baja mucho el coste por libro. Por encima de
# 20-25 la ganancia se aplana y crece el riesgo de que la respuesta se trunque
# y de perder mas libros si falla una llamada.
#
# Medido en 3.22.0: la parte fija son 28.926 caracteres (eran 32.677 antes de
# comprimir el prompt y agrupar los temas por eje). A 20 libros por llamada son
# ~1.450 caracteres fijos por libro. OJO: esa cifra crece sola cada vez que se
# anaden temas al vocabulario -de 120 a 151 temas subio un 60%-, asi que si se
# vuelve a engordar, revisar este numero. Desde 3.22.0 la parte fija viaja en
# el mensaje `system`, que es lo que cachean los proveedores: el resumen del
# rescate dice cuantos tokens vinieron de cache.
prefs.defaults['llm_batch']       = 20
# Cuanto puede pasarse un lote del tamano de arriba para no tener que abrir
# otra llamada. El coste de una llamada es casi todo parte FIJA (~19.500
# caracteres de reglas, mapa y temas), asi que 21 libros en una llamada salen
# a un tercio menos que 20+1 en dos. Con 0.25 el techo real es 25 libros; por
# encima se empieza a rozar el limite de tokens de la respuesta y el modelo
# atiende peor al final del lote. Ver plan_rescue_chunks.
prefs.defaults['llm_batch_tolerancia'] = 0.25
prefs.defaults['llm_min_conf']    = 0.55
prefs.defaults['llm_write_temas'] = True
prefs.defaults['llm_write_reason'] = True
prefs.defaults['llm_reason_field'] = '#motivo_ia'
prefs.defaults['llm_write_serie'] = True
prefs.defaults['llm_serie_field'] = '#serie_ia'
prefs.defaults['llm_write_conf']  = True
prefs.defaults['llm_conf_field']  = '#confianza_ia'

# Campo dedicado a la clasificacion de la IA en la nube (separado del campo
# principal ml_library_field): el rescate escribe AQUI, nunca en el campo
# principal. La clasificacion local puede LEER este campo para promover su
# valor al campo principal si la confianza es muy alta (ver llm_promote_*),
# pero nunca escribe en el.
prefs.defaults['llm_library_field']  = '#libreria_ia'
prefs.defaults['llm_library_prefix'] = 'Biblioteca IA: '
# Campo dedicado a los TEMAS que detecta la IA en la nube, separado del campo
# de temas del motor local (`ml_mood_field`). Hasta 3.9.0 el rescate escribia
# sus temas en ESE mismo campo y, con overwrite activo, borraba los que habia
# puesto el motor local por regex sin dejar rastro de cual venia de donde. Con
# un campo propio se pueden comparar los dos y usar las diferencias para
# mejorar los patrones de mood_rules.json. Si se deja VACIO se vuelve al
# comportamiento anterior (escribir en `ml_mood_field`).
prefs.defaults['llm_temas_field']  = '#temas_ia'
prefs.defaults['llm_temas_prefix'] = 'Tema IA: '
# Promocion del valor de llm_library_field al campo principal durante la
# clasificacion local, solo si su confianza (llm_conf_field/100) supera este
# umbral (mas estricto que llm_min_conf, que solo decide si el rescate
# resuelve el residuo). Nunca sobreescribe llm_library_field.
prefs.defaults['llm_promote_enabled']   = True
# Idem para los TEMAS: los que la IA dejo en `llm_temas_field` SUSTITUYEN a
# los que detecta el motor local por regex, con el mismo umbral de confianza.
# Se validan contra el vocabulario actual de mood_rules.json, asi que un
# nombre de una version anterior no resucita en el campo bueno.
prefs.defaults['llm_promote_temas_enabled'] = True
prefs.defaults['llm_promote_threshold'] = 0.90

# --- Perfiles de IA en la nube -------------------------------------------
# Varios juegos de proveedor/clave/modelo/URL guardados para elegir sin
# tener que reconfigurar cada vez. Los campos sueltos de arriba
# (llm_provider/llm_api_key/llm_model/llm_base_url) se mantienen como
# ESPEJO del perfil activo: el resto del plugin (accion del menu, "Probar
# conexion") los sigue leyendo tal cual, sin enterarse de que existen
# perfiles.
prefs.defaults['llm_profiles'] = []
prefs.defaults['llm_active_profile'] = ''


def _migrate_single_profile_if_needed():
    """La primera vez que se usa esta version, convierte la config suelta
    (la de antes de tener perfiles) en un perfil "Por defecto". Se ejecuta
    una sola vez: en cuanto hay algo en llm_profiles no vuelve a tocar nada.
    """
    if prefs['llm_profiles']:
        return
    prefs['llm_profiles'] = [{
        'name': 'Por defecto',
        'provider': prefs.get('llm_provider', 'glm'),
        'api_key':  prefs.get('llm_api_key', ''),
        'model':    prefs.get('llm_model', ''),
        'base_url': prefs.get('llm_base_url', ''),
    }]
    prefs['llm_active_profile'] = 'Por defecto'


def list_profiles():
    _migrate_single_profile_if_needed()
    return prefs['llm_profiles']


def get_active_profile_name():
    _migrate_single_profile_if_needed()
    names = [p['name'] for p in prefs['llm_profiles']]
    active = prefs['llm_active_profile']
    if active not in names:
        active = names[0] if names else ''
        prefs['llm_active_profile'] = active
    return active


def get_profile(name):
    for p in list_profiles():
        if p['name'] == name:
            return p
    return None


def apply_profile(name):
    """Activa un perfil ya guardado: lo marca como activo y vuelca sus
    datos en los campos sueltos (espejo) que lee el resto del plugin."""
    profile = get_profile(name)
    if not profile:
        return False
    prefs['llm_active_profile'] = name
    prefs['llm_provider']  = profile.get('provider', 'glm')
    prefs['llm_api_key']   = profile.get('api_key', '')
    prefs['llm_model']     = profile.get('model', '')
    prefs['llm_base_url']  = profile.get('base_url', '')
    return True


def save_profile(name, provider, api_key, model, base_url):
    """Crea el perfil si no existia, o actualiza el que ya tenia ese
    nombre. Lo deja activo (y actualiza el espejo via apply_profile)."""
    name = (name or '').strip()
    if not name:
        return False
    profiles = list_profiles()
    new_list = []
    found = False
    for p in profiles:
        if p['name'] == name:
            new_list.append({'name': name, 'provider': provider,
                              'api_key': api_key, 'model': model,
                              'base_url': base_url})
            found = True
        else:
            new_list.append(p)
    if not found:
        new_list.append({'name': name, 'provider': provider,
                          'api_key': api_key, 'model': model,
                          'base_url': base_url})
    prefs['llm_profiles'] = new_list
    apply_profile(name)
    return True


def rename_profile(old_name, new_name):
    new_name = (new_name or '').strip()
    if not new_name or old_name == new_name:
        return False
    profiles = list_profiles()
    if any(p['name'] == new_name for p in profiles):
        return False  # ya existe un perfil con ese nombre
    changed = False
    for p in profiles:
        if p['name'] == old_name:
            p['name'] = new_name
            changed = True
    if not changed:
        return False
    prefs['llm_profiles'] = profiles
    if prefs['llm_active_profile'] == old_name:
        prefs['llm_active_profile'] = new_name
    return True


def delete_profile(name):
    """No deja borrar el ultimo perfil que quede. Si se borra el activo,
    activa otro (el primero que quede)."""
    profiles = list_profiles()
    if len(profiles) <= 1:
        return False
    new_list = [p for p in profiles if p['name'] != name]
    if len(new_list) == len(profiles):
        return False
    prefs['llm_profiles'] = new_list
    if prefs['llm_active_profile'] == name:
        apply_profile(new_list[0]['name'])
    return True


class ConfigWidget(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()
        self._load_values()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        outer.addWidget(scroll)

        inner = QWidget()
        scroll.setWidget(inner)
        layout = QVBoxLayout(inner)

        # --- Campos de análisis ---
        grp_source = QGroupBox('Campos de análisis (texto de entrada al modelo)')
        source_layout = QVBoxLayout(grp_source)
        self._source_checks = {}
        for key, label in STANDARD_FIELDS:
            chk = QCheckBox(label)
            self._source_checks[key] = chk
            source_layout.addWidget(chk)
        self.chk_subtitle = QCheckBox('Subtítulo (columna personalizada)')
        source_layout.addWidget(self.chk_subtitle)
        row_sub = QHBoxLayout()
        row_sub.addWidget(QLabel('Columna del subtítulo:'))
        self.txt_subtitle_field = QLineEdit()
        self.txt_subtitle_field.setPlaceholderText('#subtitle')
        row_sub.addWidget(self.txt_subtitle_field)
        source_layout.addLayout(row_sub)
        layout.addWidget(grp_source)

        # --- Qué escribir ---
        grp_w = QGroupBox('Qué escribir')
        wl = QVBoxLayout(grp_w)
        self.chk_ml_library = QCheckBox('Escribir librería sugerida (eje 1)')
        self.chk_ml_moods   = QCheckBox('Escribir tags de tema / tropos (eje 2)')
        self.chk_ml_overwrite = QCheckBox('Reemplazar etiquetas previas del plugin (Biblioteca:/Tema:)')
        wl.addWidget(self.chk_ml_library)
        wl.addWidget(self.chk_ml_moods)
        wl.addWidget(self.chk_ml_overwrite)
        layout.addWidget(grp_w)

        # --- Campos destino ---
        grp_dst = QGroupBox('Campos destino')
        dl = QVBoxLayout(grp_dst)

        row_lib = QHBoxLayout()
        row_lib.addWidget(QLabel('Campo de la librería:'))
        self.combo_ml_libfield = QComboBox()
        self.combo_ml_libfield.addItems(['tags', '#libreria', '#biblioteca', '#genre'])
        self.combo_ml_libfield.setEditable(True)
        row_lib.addWidget(self.combo_ml_libfield)
        dl.addLayout(row_lib)

        row_mood = QHBoxLayout()
        row_mood.addWidget(QLabel('Campo de los temas:'))
        self.combo_ml_moodfield = QComboBox()
        self.combo_ml_moodfield.addItems(['tags', '#tema'])
        self.combo_ml_moodfield.setEditable(True)
        row_mood.addWidget(self.combo_ml_moodfield)
        dl.addLayout(row_mood)

        row_th = QHBoxLayout()
        row_th.addWidget(QLabel('Confianza mínima (0–1), si no → "(revisar)":'))
        self.txt_ml_threshold = QLineEdit()
        self.txt_ml_threshold.setPlaceholderText('0.55')
        self.txt_ml_threshold.setMaximumWidth(90)
        row_th.addWidget(self.txt_ml_threshold)
        dl.addLayout(row_th)
        layout.addWidget(grp_dst)

        # --- Unificación por serie / universo / autor ---
        grp_grp = QGroupBox('Coherencia entre libros')
        gl = QVBoxLayout(grp_grp)
        self.chk_group_unify = QCheckBox('Misma librería para toda la serie/universo')
        self.chk_group_moods = QCheckBox('Unir los tags de tema de todo el grupo')
        gl.addWidget(self.chk_group_unify)
        gl.addWidget(self.chk_group_moods)
        row_u = QHBoxLayout()
        row_u.addWidget(QLabel('Columna de universo:'))
        self.txt_universe = QLineEdit()
        self.txt_universe.setPlaceholderText('#world')
        row_u.addWidget(self.txt_universe)
        gl.addLayout(row_u)
        gl.addWidget(QLabel('<small>Manda el universo; si está vacío, agrupa por serie. '
                            'Gana la librería de mayor confianza sumada del grupo.</small>'))

        self.chk_author = QCheckBox('Para los dudosos, usar la librería dominante del autor')
        gl.addWidget(self.chk_author)
        row_a = QHBoxLayout()
        row_a.addWidget(QLabel('Mayoría mínima del autor (0–1):'))
        self.txt_author_dom = QLineEdit()
        self.txt_author_dom.setPlaceholderText('0.6')
        self.txt_author_dom.setMaximumWidth(70)
        row_a.addWidget(self.txt_author_dom)
        gl.addLayout(row_a)
        layout.addWidget(grp_grp)

        # --- Rescate con IA en la nube (capa híbrida, opcional) ---
        grp_llm = QGroupBox('Rescate con IA en la nube (opcional, para los "(revisar)")')
        ll = QVBoxLayout(grp_llm)
        lbl_llm_info = QLabel(
            '<small>Solo se usa con el menu <b>"Rescatar con IA..."</b>. Manda los '
            'libros no clasificados a un LLM (GLM, DeepSeek...). Requiere clave y '
            'conexion; el resto del plugin sigue funcionando sin internet. La clave '
            'se guarda en la config local del plugin.</small>')
        lbl_llm_info.setWordWrap(True)
        ll.addWidget(lbl_llm_info)

        row_profile = QHBoxLayout()
        row_profile.addWidget(QLabel('Perfil guardado:'))
        self.combo_llm_profile = QComboBox()
        self.combo_llm_profile.currentIndexChanged.connect(self._on_profile_selected)
        row_profile.addWidget(self.combo_llm_profile, 1)
        self.btn_profile_new = QPushButton('Guardar como nuevo...')
        self.btn_profile_new.clicked.connect(self._new_profile)
        row_profile.addWidget(self.btn_profile_new)
        self.btn_profile_rename = QPushButton('Renombrar...')
        self.btn_profile_rename.clicked.connect(self._rename_profile)
        row_profile.addWidget(self.btn_profile_rename)
        self.btn_profile_delete = QPushButton('Borrar')
        self.btn_profile_delete.clicked.connect(self._delete_profile)
        row_profile.addWidget(self.btn_profile_delete)
        ll.addLayout(row_profile)
        lbl_profile_hint = QLabel(
            '<small>Cada perfil guarda proveedor, clave, modelo y URL. Cambiar '
            'el combo carga esos datos en los campos de abajo (sin guardarlos '
            'todavia); <b>Aceptar</b> los guarda en el perfil seleccionado. '
            'Tambien se puede cambiar de perfil activo desde el menu del '
            'plugin ("Perfil de IA activo"), sin abrir este dialogo.</small>')
        lbl_profile_hint.setWordWrap(True)
        ll.addWidget(lbl_profile_hint)

        row_prov = QHBoxLayout()
        row_prov.addWidget(QLabel('Proveedor:'))
        self.combo_llm_provider = QComboBox()
        self.combo_llm_provider.addItems(
            ['glm', 'google', 'deepseek', 'openai', 'anthropic', 'kimi', 'qwen',
             'openrouter', 'groq', 'mistral', 'cerebras', 'together',
             'local', 'otro'])
        row_prov.addWidget(self.combo_llm_provider)
        ll.addLayout(row_prov)

        row_key = QHBoxLayout()
        row_key.addWidget(QLabel('Clave API:'))
        self.txt_llm_key = QLineEdit()
        self.txt_llm_key.setEchoMode(QLineEdit.EchoMode.Password)
        row_key.addWidget(self.txt_llm_key)
        ll.addLayout(row_key)

        row_mod = QHBoxLayout()
        row_mod.addWidget(QLabel('Modelo (vacio = por defecto del proveedor):'))
        self.txt_llm_model = QLineEdit()
        self.txt_llm_model.setPlaceholderText('glm-4.5-flash')
        self.txt_llm_model.setMaximumWidth(240)
        row_mod.addWidget(self.txt_llm_model)
        ll.addLayout(row_mod)

        row_url = QHBoxLayout()
        row_url.addWidget(QLabel('URL del servidor:'))
        self.txt_llm_base = QLineEdit()
        self.txt_llm_base.setPlaceholderText('(vacio = la del proveedor elegido)')
        row_url.addWidget(self.txt_llm_base)
        ll.addLayout(row_url)
        lbl_url_hint = QLabel(
            '<small>Solo hace falta para el proveedor <b>otro</b>: cualquier '
            'servidor que hable el protocolo de OpenAI (la URL termina donde '
            'empezaria /chat/completions, p.ej. '
            'https://openrouter.ai/api/v1). Rellenala tambien si quieres '
            'apuntar uno de los conocidos a otro sitio. Los proveedores nuevos '
            '(openrouter, groq, mistral, cerebras, together) NO traen modelo '
            'por defecto: escribe el nombre exacto en "Modelo", porque sus '
            'catalogos cambian cada pocos meses.</small>')
        lbl_url_hint.setWordWrap(True)
        ll.addWidget(lbl_url_hint)

        row_bt = QHBoxLayout()
        row_bt.addWidget(QLabel('Libros por llamada:'))
        self.txt_llm_batch = QLineEdit()
        self.txt_llm_batch.setPlaceholderText('20')
        self.txt_llm_batch.setMaximumWidth(70)
        row_bt.addWidget(self.txt_llm_batch)
        row_bt.addWidget(QLabel('Confianza minima:'))
        self.txt_llm_minconf = QLineEdit()
        self.txt_llm_minconf.setPlaceholderText('0.55')
        self.txt_llm_minconf.setMaximumWidth(70)
        row_bt.addWidget(self.txt_llm_minconf)
        ll.addLayout(row_bt)

        row_libia = QHBoxLayout()
        row_libia.addWidget(QLabel('Columna de la libreria detectada por la IA:'))
        self.txt_llm_library_field = QLineEdit()
        self.txt_llm_library_field.setPlaceholderText('#libreria_ia')
        row_libia.addWidget(self.txt_llm_library_field)
        ll.addLayout(row_libia)
        lbl_libia_hint = QLabel(
            '<small>Columna PROPIA de la IA, separada del campo de libreria de la '
            'clasificacion local (arriba, en "Campos destino"). El rescate escribe '
            'aqui su resultado; la clasificacion local puede leerlo (ver mas abajo '
            '"Promocion a la clasificacion principal") pero nunca escribe en esta '
            'columna. Crea una columna de texto personalizada si usas el nombre por '
            'defecto.</small>')
        lbl_libia_hint.setWordWrap(True)
        ll.addWidget(lbl_libia_hint)

        self.chk_llm_temas = QCheckBox('Escribir tambien los temas detectados por la IA')
        ll.addWidget(self.chk_llm_temas)
        row_temasia = QHBoxLayout()
        row_temasia.addWidget(QLabel('Columna de los temas de la IA:'))
        self.txt_llm_temas_field = QLineEdit()
        self.txt_llm_temas_field.setPlaceholderText('#temas_ia')
        row_temasia.addWidget(self.txt_llm_temas_field)
        ll.addLayout(row_temasia)
        lbl_temasia_hint = QLabel(
            '<small>Columna PROPIA de la IA para los temas, separada de la del '
            'motor local ("Campo de los temas", arriba). Creala como columna '
            'personalizada de texto separado por comas y mostrada en el '
            'navegador de etiquetas. Si la dejas VACIA, la IA vuelve a escribir '
            'sus temas en el campo del motor local y sustituye los que hubiera '
            'puesto por regex.</small>')
        lbl_temasia_hint.setWordWrap(True)
        ll.addWidget(lbl_temasia_hint)

        self.chk_llm_reason = QCheckBox('Guardar el motivo de la IA en una columna personalizada')
        ll.addWidget(self.chk_llm_reason)
        row_reason = QHBoxLayout()
        row_reason.addWidget(QLabel('Columna del motivo:'))
        self.txt_llm_reason_field = QLineEdit()
        self.txt_llm_reason_field.setPlaceholderText('#motivo_ia')
        row_reason.addWidget(self.txt_llm_reason_field)
        ll.addLayout(row_reason)
        lbl_reason_hint = QLabel(
            '<small>Debe ser una columna personalizada de texto (largo) que crees tu '
            'en Preferencias -> Anadir columnas personalizadas. Ahi se guarda la '
            'explicacion breve que da el LLM para cada libro rescatado.</small>')
        lbl_reason_hint.setWordWrap(True)
        ll.addWidget(lbl_reason_hint)

        self.chk_llm_serie = QCheckBox('Guardar la serie/saga que detecte la IA (campo aparte)')
        ll.addWidget(self.chk_llm_serie)
        row_serie = QHBoxLayout()
        row_serie.addWidget(QLabel('Columna de la serie IA:'))
        self.txt_llm_serie_field = QLineEdit()
        self.txt_llm_serie_field.setPlaceholderText('#serie_ia')
        row_serie.addWidget(self.txt_llm_serie_field)
        ll.addLayout(row_serie)

        self.chk_llm_conf = QCheckBox('Guardar el % de confianza de la clasificacion IA')
        ll.addWidget(self.chk_llm_conf)
        row_conf = QHBoxLayout()
        row_conf.addWidget(QLabel('Columna de la confianza:'))
        self.txt_llm_conf_field = QLineEdit()
        self.txt_llm_conf_field.setPlaceholderText('#confianza_ia')
        row_conf.addWidget(self.txt_llm_conf_field)
        ll.addLayout(row_conf)
        lbl_conf_hint = QLabel(
            '<small>La serie va a una columna de texto (no toca la serie real de '
            'Calibre). La confianza es un entero 0-100: crea una columna '
            'personalizada de tipo <b>numero entero</b>. Solo se rellenan los libros '
            'que la IA resuelve.</small>')
        lbl_conf_hint.setWordWrap(True)
        ll.addWidget(lbl_conf_hint)

        self.chk_llm_promote = QCheckBox(
            'Promocion a la clasificacion principal: usar la libreria IA como '
            'clasificacion si su confianza supera el umbral')
        ll.addWidget(self.chk_llm_promote)
        row_promote = QHBoxLayout()
        row_promote.addWidget(QLabel('Umbral de promocion (0-1):'))
        self.txt_llm_promote_threshold = QLineEdit()
        self.txt_llm_promote_threshold.setPlaceholderText('0.90')
        self.txt_llm_promote_threshold.setMaximumWidth(70)
        row_promote.addWidget(self.txt_llm_promote_threshold)
        ll.addLayout(row_promote)
        lbl_promote_hint = QLabel(
            '<small>Al lanzar "Clasificar" (IA local), si un libro ya tiene un valor '
            'en la columna de libreria IA de arriba con esa confianza minima, se usa '
            'directamente como clasificacion (nivel adicional, antes del consenso de '
            'grupo/autor). La columna de la IA NUNCA se sobreescribe en este paso; '
            'solo se lee. Umbral recomendado alto (0.85-0.95): mas estricto que la '
            'confianza minima del rescate, que solo decide si la IA resuelve el '
            'residuo.</small>')
        lbl_promote_hint.setWordWrap(True)
        ll.addWidget(lbl_promote_hint)

        self.btn_llm_test = QPushButton('Probar conexion')
        self.btn_llm_test.clicked.connect(self._test_llm)
        ll.addWidget(self.btn_llm_test)
        layout.addWidget(grp_llm)

        info = QLabel(
            "<small>El modelo (<b>model_weights.json</b>) y las reglas de tema "
            "(<b>mood_rules.json</b>) se cargan del plugin, o de la carpeta de "
            f"configuración de Calibre si los pones ahí:<br><b>{config_dir}</b></small>")
        info.setWordWrap(True)
        layout.addWidget(info)

    def _refresh_profile_combo(self, select=None):
        self.combo_llm_profile.blockSignals(True)
        self.combo_llm_profile.clear()
        names = [p['name'] for p in list_profiles()]
        self.combo_llm_profile.addItems(names)
        target = select or get_active_profile_name()
        if target in names:
            self.combo_llm_profile.setCurrentText(target)
        self.combo_llm_profile.blockSignals(False)
        self._on_profile_selected(self.combo_llm_profile.currentIndex())

    def _on_profile_selected(self, index):
        name = self.combo_llm_profile.currentText()
        if not name:
            return
        profile = get_profile(name)
        if not profile:
            return
        self.combo_llm_provider.setCurrentText(profile.get('provider', 'glm'))
        self.txt_llm_key.setText(profile.get('api_key', ''))
        self.txt_llm_model.setText(profile.get('model', ''))
        self.txt_llm_base.setText(profile.get('base_url', ''))

    def _new_profile(self):
        name, ok = QInputDialog.getText(self, 'Nuevo perfil', 'Nombre del perfil:')
        name = (name or '').strip()
        if not ok or not name:
            return
        if get_profile(name):
            QMessageBox.warning(self, 'Perfil', 'Ya existe un perfil con ese nombre.')
            return
        save_profile(
            name,
            self.combo_llm_provider.currentText().strip() or 'glm',
            self.txt_llm_key.text().strip(),
            self.txt_llm_model.text().strip(),
            self.txt_llm_base.text().strip())
        self._refresh_profile_combo(select=name)

    def _rename_profile(self):
        old = self.combo_llm_profile.currentText()
        if not old:
            return
        new, ok = QInputDialog.getText(self, 'Renombrar perfil', 'Nuevo nombre:', text=old)
        new = (new or '').strip()
        if not ok or not new or new == old:
            return
        if not rename_profile(old, new):
            QMessageBox.warning(self, 'Perfil', 'No se pudo renombrar (¿nombre repetido?).')
            return
        self._refresh_profile_combo(select=new)

    def _delete_profile(self):
        name = self.combo_llm_profile.currentText()
        if not name:
            return
        if len(list_profiles()) <= 1:
            QMessageBox.warning(self, 'Perfil', 'No se puede borrar el unico perfil que queda.')
            return
        resp = QMessageBox.question(
            self, 'Borrar perfil', 'Borrar el perfil "{}"?'.format(name))
        if resp != QMessageBox.StandardButton.Yes:
            return
        if delete_profile(name):
            self._refresh_profile_combo()

    def _test_llm(self):
        provider = self.combo_llm_provider.currentText().strip() or 'glm'
        key = self.txt_llm_key.text().strip()
        model = self.txt_llm_model.text().strip() or None
        base = self.txt_llm_base.text().strip() or None
        try:
            from calibre_plugins.book_classifier import llm_rescue_engine as eng
            ok, msg = eng.test_connection(provider, key, model=model, base=base)
        except Exception as e:
            ok, msg = False, str(e)
        if ok:
            QMessageBox.information(self, 'Conexion IA', 'Funciona. Respuesta: ' + (msg or 'OK'))
        else:
            QMessageBox.warning(self, 'Conexion IA', 'Fallo:\n' + msg)

    def _load_values(self):
        active = prefs['source_fields']
        for key, chk in self._source_checks.items():
            chk.setChecked(key in active)
        self.chk_subtitle.setChecked(prefs['ml_use_subtitle'])
        self.txt_subtitle_field.setText(prefs['ml_subtitle_field'])
        self.chk_ml_library.setChecked(prefs['ml_write_library'])
        self.chk_ml_moods.setChecked(prefs['ml_write_moods'])
        self.chk_ml_overwrite.setChecked(prefs['ml_overwrite'])
        self.combo_ml_libfield.setEditText(prefs['ml_library_field'])
        self.combo_ml_moodfield.setEditText(prefs['ml_mood_field'])
        self.txt_ml_threshold.setText(str(prefs['ml_threshold']))
        self.chk_group_unify.setChecked(prefs['ml_group_unify'])
        self.chk_group_moods.setChecked(prefs['ml_group_unify_moods'])
        self.txt_universe.setText(prefs['ml_universe_field'])
        self.chk_author.setChecked(prefs['ml_author_fallback'])
        self.txt_author_dom.setText(str(prefs['ml_author_dominance']))
        self._refresh_profile_combo()
        self.txt_llm_batch.setText(str(prefs['llm_batch']))
        self.txt_llm_minconf.setText(str(prefs['llm_min_conf']))
        self.txt_llm_library_field.setText(prefs['llm_library_field'])
        self.chk_llm_temas.setChecked(prefs['llm_write_temas'])
        self.txt_llm_temas_field.setText(prefs['llm_temas_field'])
        self.chk_llm_reason.setChecked(prefs['llm_write_reason'])
        self.txt_llm_reason_field.setText(prefs['llm_reason_field'])
        self.chk_llm_serie.setChecked(prefs['llm_write_serie'])
        self.txt_llm_serie_field.setText(prefs['llm_serie_field'])
        self.chk_llm_conf.setChecked(prefs['llm_write_conf'])
        self.txt_llm_conf_field.setText(prefs['llm_conf_field'])
        self.chk_llm_promote.setChecked(prefs['llm_promote_enabled'])
        self.txt_llm_promote_threshold.setText(str(prefs['llm_promote_threshold']))

    def save_settings(self):
        prefs['source_fields'] = [k for k, c in self._source_checks.items() if c.isChecked()]
        prefs['ml_use_subtitle']   = self.chk_subtitle.isChecked()
        prefs['ml_subtitle_field'] = self.txt_subtitle_field.text().strip() or '#subtitle'
        prefs['ml_write_library'] = self.chk_ml_library.isChecked()
        prefs['ml_write_moods']   = self.chk_ml_moods.isChecked()
        prefs['ml_overwrite']     = self.chk_ml_overwrite.isChecked()
        prefs['ml_library_field'] = self.combo_ml_libfield.currentText().strip() or 'tags'
        prefs['ml_mood_field']    = self.combo_ml_moodfield.currentText().strip() or 'tags'
        try:
            prefs['ml_threshold'] = max(0.0, min(1.0, float(self.txt_ml_threshold.text().strip() or '0.55')))
        except ValueError:
            prefs['ml_threshold'] = 0.55
        prefs['ml_group_unify']       = self.chk_group_unify.isChecked()
        prefs['ml_group_unify_moods'] = self.chk_group_moods.isChecked()
        prefs['ml_universe_field']    = self.txt_universe.text().strip() or '#universe'
        prefs['ml_author_fallback']   = self.chk_author.isChecked()
        try:
            prefs['ml_author_dominance'] = max(0.0, min(1.0, float(self.txt_author_dom.text().strip() or '0.6')))
        except ValueError:
            prefs['ml_author_dominance'] = 0.6
        # Guarda los campos actuales en el perfil seleccionado en el combo
        # (lo crea si el nombre no existiera todavia) y lo deja activo;
        # save_profile actualiza tambien los campos sueltos (espejo) que
        # lee el resto del plugin.
        active_name = self.combo_llm_profile.currentText().strip() or get_active_profile_name()
        save_profile(
            active_name,
            self.combo_llm_provider.currentText().strip() or 'glm',
            self.txt_llm_key.text().strip(),
            self.txt_llm_model.text().strip(),
            self.txt_llm_base.text().strip())
        self._refresh_profile_combo(select=active_name)
        try:
            prefs['llm_batch'] = max(1, min(50, int(self.txt_llm_batch.text().strip() or '20')))
        except ValueError:
            prefs['llm_batch'] = 20
        try:
            prefs['llm_min_conf'] = max(0.0, min(1.0, float(self.txt_llm_minconf.text().strip() or '0.55')))
        except ValueError:
            prefs['llm_min_conf'] = 0.55
        prefs['llm_library_field'] = self.txt_llm_library_field.text().strip() or '#libreria_ia'
        prefs['llm_write_temas'] = self.chk_llm_temas.isChecked()
        # Vacio a proposito = comportamiento anterior (escribir en ml_mood_field),
        # asi que aqui NO se pone un valor por defecto si el usuario lo borra.
        prefs['llm_temas_field'] = self.txt_llm_temas_field.text().strip()
        prefs['llm_write_reason'] = self.chk_llm_reason.isChecked()
        prefs['llm_reason_field'] = self.txt_llm_reason_field.text().strip() or '#motivo_ia'
        prefs['llm_write_serie'] = self.chk_llm_serie.isChecked()
        prefs['llm_serie_field'] = self.txt_llm_serie_field.text().strip() or '#serie_ia'
        prefs['llm_write_conf']  = self.chk_llm_conf.isChecked()
        prefs['llm_conf_field']  = self.txt_llm_conf_field.text().strip() or '#confianza_ia'
        prefs['llm_promote_enabled'] = self.chk_llm_promote.isChecked()
        try:
            prefs['llm_promote_threshold'] = max(0.0, min(1.0, float(
                self.txt_llm_promote_threshold.text().strip() or '0.90')))
        except ValueError:
            prefs['llm_promote_threshold'] = 0.90


def show_config_dialog(gui):
    from qt.core import QDialog, QVBoxLayout, QDialogButtonBox
    dialog = QDialog(gui)
    dialog.setWindowTitle('Configurar Book Classifier (IA)')
    dialog.resize(560, 640)
    layout = QVBoxLayout(dialog)
    widget = ConfigWidget()
    layout.addWidget(widget)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        widget.save_settings()
