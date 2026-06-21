# -*- coding: utf-8 -*-
"""
Configuración del plugin (clasificación con IA local).
"""

from qt.core import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QCheckBox, QGroupBox, QLineEdit, QScrollArea
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
        self.combo_ml_libfield.addItems(['tags', '#libreria', '#genre'])
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
        self.txt_universe.setPlaceholderText('#universe')
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
        row_a.addWidget(self.txt_author_dom)
        gl.addLayout(row_a)
        layout.addWidget(grp_grp)

        info = QLabel(
            "<small>El modelo (<b>model_weights.json</b>) y las reglas de tema "
            "(<b>mood_rules.json</b>) se cargan del plugin, o de la carpeta de "
            f"configuración de Calibre si los pones ahí:<br><b>{config_dir}</b></small>")
        info.setWordWrap(True)
        layout.addWidget(info)

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


def show_config_dialog(gui):
    from qt.core import QDialog, QVBoxLayout, QDialogButtonBox
    dialog = QDialog(gui)
    dialog.setWindowTitle('Configurar Book Classifier (IA)')
    layout = QVBoxLayout(dialog)
    widget = ConfigWidget()
    layout.addWidget(widget)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        widget.save_settings()
