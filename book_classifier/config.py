# -*- coding: utf-8 -*-
"""
Configuración del plugin (clasificación con IA local).
"""

from qt.core import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QCheckBox, QGroupBox, QLineEdit, QScrollArea, QPushButton, QMessageBox
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
prefs.defaults['llm_batch']       = 10
prefs.defaults['llm_min_conf']    = 0.55
prefs.defaults['llm_write_temas'] = True
prefs.defaults['llm_write_reason'] = True
prefs.defaults['llm_reason_field'] = '#motivo_ia'
prefs.defaults['llm_write_serie'] = True
prefs.defaults['llm_serie_field'] = '#serie_ia'
prefs.defaults['llm_write_conf']  = True
prefs.defaults['llm_conf_field']  = '#confianza_ia'


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

        row_prov = QHBoxLayout()
        row_prov.addWidget(QLabel('Proveedor:'))
        self.combo_llm_provider = QComboBox()
        self.combo_llm_provider.addItems(
            ['glm', 'deepseek', 'openai', 'google', 'kimi', 'qwen', 'anthropic', 'local'])
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

        row_bt = QHBoxLayout()
        row_bt.addWidget(QLabel('Libros por llamada:'))
        self.txt_llm_batch = QLineEdit()
        self.txt_llm_batch.setPlaceholderText('10')
        self.txt_llm_batch.setMaximumWidth(70)
        row_bt.addWidget(self.txt_llm_batch)
        row_bt.addWidget(QLabel('Confianza minima:'))
        self.txt_llm_minconf = QLineEdit()
        self.txt_llm_minconf.setPlaceholderText('0.55')
        self.txt_llm_minconf.setMaximumWidth(70)
        row_bt.addWidget(self.txt_llm_minconf)
        ll.addLayout(row_bt)

        self.chk_llm_temas = QCheckBox('Escribir tambien los temas detectados por la IA')
        ll.addWidget(self.chk_llm_temas)

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

    def _test_llm(self):
        provider = self.combo_llm_provider.currentText().strip() or 'glm'
        key = self.txt_llm_key.text().strip()
        model = self.txt_llm_model.text().strip() or None
        try:
            from calibre_plugins.book_classifier import llm_rescue_engine as eng
            ok, msg = eng.test_connection(provider, key, model=model)
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
        self.combo_llm_provider.setCurrentText(prefs['llm_provider'])
        self.txt_llm_key.setText(prefs['llm_api_key'])
        self.txt_llm_model.setText(prefs['llm_model'])
        self.txt_llm_batch.setText(str(prefs['llm_batch']))
        self.txt_llm_minconf.setText(str(prefs['llm_min_conf']))
        self.chk_llm_temas.setChecked(prefs['llm_write_temas'])
        self.chk_llm_reason.setChecked(prefs['llm_write_reason'])
        self.txt_llm_reason_field.setText(prefs['llm_reason_field'])
        self.chk_llm_serie.setChecked(prefs['llm_write_serie'])
        self.txt_llm_serie_field.setText(prefs['llm_serie_field'])
        self.chk_llm_conf.setChecked(prefs['llm_write_conf'])
        self.txt_llm_conf_field.setText(prefs['llm_conf_field'])

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
        prefs['llm_provider'] = self.combo_llm_provider.currentText().strip() or 'glm'
        prefs['llm_api_key']  = self.txt_llm_key.text().strip()
        prefs['llm_model']    = self.txt_llm_model.text().strip()
        try:
            prefs['llm_batch'] = max(1, min(50, int(self.txt_llm_batch.text().strip() or '10')))
        except ValueError:
            prefs['llm_batch'] = 10
        try:
            prefs['llm_min_conf'] = max(0.0, min(1.0, float(self.txt_llm_minconf.text().strip() or '0.55')))
        except ValueError:
            prefs['llm_min_conf'] = 0.55
        prefs['llm_write_temas'] = self.chk_llm_temas.isChecked()
        prefs['llm_write_reason'] = self.chk_llm_reason.isChecked()
        prefs['llm_reason_field'] = self.txt_llm_reason_field.text().strip() or '#motivo_ia'
        prefs['llm_write_serie'] = self.chk_llm_serie.isChecked()
        prefs['llm_serie_field'] = self.txt_llm_serie_field.text().strip() or '#serie_ia'
        prefs['llm_write_conf']  = self.chk_llm_conf.isChecked()
        prefs['llm_conf_field']  = self.txt_llm_conf_field.text().strip() or '#confianza_ia'


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
