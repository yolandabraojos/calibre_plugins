# -*- coding: utf-8 -*-
"""
Configuración del plugin: interfaz gráfica + almacenamiento de preferencias.
"""

import json
from qt.core import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QPlainTextEdit, QComboBox, QCheckBox, QGroupBox, QFileDialog,
    QLineEdit, QScrollArea, QSizePolicy, Qt, QFont, QMessageBox
)
from calibre.utils.config import JSONConfig

# ─── Valores por defecto ───────────────────────────────────────────────────────

DEFAULT_RULES = {
    "categories": [
        {
            "name": "Romance Regencia",
            "require_all": False,
            "min_keywords_match": 1,
            "keywords": ["regencia", "regency", "romance", "ton", "temporada social"],
            "exclude_keywords": ["paranormal", "ciencia ficcion"],
            "priority": 10
        },
        {
            "name": "Romance Histórico",
            "require_all": False,
            "min_keywords_match": 1,
            "keywords": ["historico", "historical", "romance", "victoriana", "tudor", "medieval"],
            "exclude_keywords": [],
            "priority": 8
        },
        {
            "name": "Fantasía Épica",
            "require_all": False,
            "min_keywords_match": 2,
            "keywords": ["fantasia", "fantasy", "épico", "dragon", "magia", "quest"],
            "exclude_keywords": ["romance"],
            "priority": 9
        },
        {
            "name": "Ciencia Ficción",
            "require_all": False,
            "min_keywords_match": 1,
            "keywords": ["ciencia ficcion", "science fiction", "sci-fi", "espacio", "futuro", "robot"],
            "exclude_keywords": [],
            "priority": 9
        },
        {
            "name": "Thriller",
            "require_all": True,
            "min_keywords_match": 1,
            "keywords": ["thriller", "suspense"],
            "exclude_keywords": [],
            "priority": 7
        }
    ],
    "options": {
        "case_sensitive": False,
        "whole_word": True,
        "allow_multiple": True
    }
}

# Campos estándar disponibles (clave interna → etiqueta legible)
STANDARD_FIELDS = [
    ('title',     'Título'),
    ('comments',  'Comentarios / Sinopsis'),
    ('tags',      'Etiquetas (tags)'),
    ('series',    'Serie'),
    ('authors',   'Autores'),
    ('publisher', 'Editorial'),
]

# Almacenamiento persistente de Calibre
prefs = JSONConfig('plugins/book_classifier')
prefs.defaults['rules']              = DEFAULT_RULES
prefs.defaults['target_field']       = 'tags'
prefs.defaults['overwrite_existing'] = False
prefs.defaults['dry_run']            = False
prefs.defaults['source_fields']      = ['title', 'comments', 'tags', 'series']
prefs.defaults['extra_fields']       = []


# ─── Widget de configuración ───────────────────────────────────────────────────

class ConfigWidget(QWidget):

    def __init__(self):
        super().__init__()
        self._build_ui()
        self._load_values()

    def _build_ui(self):
        # Scroll area so the Aceptar button is always reachable
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        outer.addWidget(scroll)

        inner = QWidget()
        scroll.setWidget(inner)

        layout = QVBoxLayout(inner)
        layout.setSpacing(6)
        layout.setContentsMargins(8, 8, 8, 8)

        # ── Sección: campos de origen ───────────────────────────────────────
        grp_source = QGroupBox('Campos que se analizan para clasificar')
        source_layout = QVBoxLayout(grp_source)
        source_layout.setSpacing(3)

        # Checkboxes en dos columnas
        self._source_checks = {}
        grid = QHBoxLayout()
        col1 = QVBoxLayout()
        col2 = QVBoxLayout()
        for i, (key, label) in enumerate(STANDARD_FIELDS):
            chk = QCheckBox(label)
            self._source_checks[key] = chk
            (col1 if i % 2 == 0 else col2).addWidget(chk)
        grid.addLayout(col1)
        grid.addLayout(col2)
        source_layout.addLayout(grid)

        # Campos personalizados adicionales
        custom_row = QHBoxLayout()
        custom_row.addWidget(QLabel('Campos personalizados:'))
        self.txt_extra = QLineEdit()
        self.txt_extra.setPlaceholderText('#mi_campo, #otro_campo')
        self.txt_extra.setToolTip(
            'Nombres de campos personalizados separados por coma. '
            'Deben empezar por #. Solo se leen campos de tipo texto.'
        )
        custom_row.addWidget(self.txt_extra)
        source_layout.addLayout(custom_row)

        layout.addWidget(grp_source)

        # ── Sección: campo destino ──────────────────────────────────────────
        grp_field = QGroupBox('Campo destino')
        grp_layout = QHBoxLayout(grp_field)
        grp_layout.addWidget(QLabel('Guardar clasificación en:'))
        self.combo_field = QComboBox()
        self.combo_field.addItems(['tags', '#genre', '#category', '#clasificacion'])
        self.combo_field.setEditable(True)
        self.combo_field.setToolTip(
            'Usa "tags" para etiquetas estándar o "#nombre_campo" para un campo personalizado'
        )
        grp_layout.addWidget(self.combo_field)
        layout.addWidget(grp_field)

        # ── Sección: opciones ───────────────────────────────────────────────
        grp_opts = QGroupBox('Opciones')
        opts_layout = QHBoxLayout(grp_opts)
        self.chk_overwrite = QCheckBox('Reemplazar clasificación existente')
        self.chk_dry_run   = QCheckBox('Modo simulación (no guarda cambios)')
        opts_layout.addWidget(self.chk_overwrite)
        opts_layout.addWidget(self.chk_dry_run)
        layout.addWidget(grp_opts)

        # ── Sección: editor JSON ────────────────────────────────────────────
        grp_rules = QGroupBox('Reglas de clasificación (JSON)')
        rules_layout = QVBoxLayout(grp_rules)

        toolbar = QHBoxLayout()
        btn_validate = QPushButton('✔ Validar')
        btn_validate.clicked.connect(self._validate_json)
        btn_reset = QPushButton('↩ Restaurar')
        btn_reset.clicked.connect(self._reset_rules)
        btn_import = QPushButton('📂 Importar')
        btn_import.clicked.connect(self._import_json)
        btn_export = QPushButton('💾 Exportar')
        btn_export.clicked.connect(self._export_json)
        for btn in (btn_validate, btn_reset, btn_import, btn_export):
            toolbar.addWidget(btn)
        rules_layout.addLayout(toolbar)

        self.txt_rules = QPlainTextEdit()
        font = QFont('Courier New', 10)
        font.setFixedPitch(True)
        self.txt_rules.setFont(font)
        self.txt_rules.setMinimumHeight(180)
        rules_layout.addWidget(self.txt_rules)

        help_label = QLabel(
            '<small>'
            '<b>keywords</b>: palabras a buscar · '
            '<b>require_all: true</b> = todas · <b>false</b> = basta una · '
            '<b>min_keywords_match</b>: mín. de coincidencias necesarias · '
            '<b>priority</b>: mayor = gana'
            '</small>'
        )
        help_label.setWordWrap(True)
        help_label.setTextFormat(Qt.RichText)
        rules_layout.addWidget(help_label)

        layout.addWidget(grp_rules)

    def _load_values(self):
        active = prefs['source_fields']
        for key, chk in self._source_checks.items():
            chk.setChecked(key in active)

        self.txt_extra.setText(', '.join(prefs['extra_fields']))

        field = prefs['target_field']
        idx = self.combo_field.findText(field)
        if idx >= 0:
            self.combo_field.setCurrentIndex(idx)
        else:
            self.combo_field.setEditText(field)

        self.chk_overwrite.setChecked(prefs['overwrite_existing'])
        self.chk_dry_run.setChecked(prefs['dry_run'])

        self.txt_rules.setPlainText(
            json.dumps(prefs['rules'], ensure_ascii=False, indent=2)
        )

    def save_settings(self):
        rules = self._parse_json()
        if rules is None:
            return

        prefs['source_fields']      = [key for key, chk in self._source_checks.items()
                                        if chk.isChecked()]
        raw_extra                   = self.txt_extra.text()
        prefs['extra_fields']       = [f.strip() for f in raw_extra.split(',')
                                        if f.strip().startswith('#')]
        prefs['target_field']       = self.combo_field.currentText().strip()
        prefs['overwrite_existing'] = self.chk_overwrite.isChecked()
        prefs['dry_run']            = self.chk_dry_run.isChecked()
        prefs['rules']              = rules

    # ─── Helpers ──────────────────────────────────────────────────────────────

    def _parse_json(self):
        try:
            return json.loads(self.txt_rules.toPlainText())
        except json.JSONDecodeError as e:
            QMessageBox.critical(self, 'JSON inválido', f'Error al parsear JSON:\n\n{e}')
            return None

    def _validate_json(self):
        rules = self._parse_json()
        if rules is None:
            return
        cats = rules.get('categories', [])
        QMessageBox.information(
            self, 'JSON válido',
            f'El JSON es válido.\n\n{len(cats)} categoría(s) definida(s):\n' +
            '\n'.join(f'  • {c.get("name", "?")} ({len(c.get("keywords", []))} keywords)'
                      for c in cats)
        )

    def _reset_rules(self):
        self.txt_rules.setPlainText(
            json.dumps(DEFAULT_RULES, ensure_ascii=False, indent=2)
        )

    def _import_json(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Importar reglas JSON', '', 'JSON (*.json)'
        )
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            json.loads(content)
            self.txt_rules.setPlainText(content)
        except Exception as e:
            QMessageBox.critical(self, 'Error al importar', str(e))

    def _export_json(self):
        rules = self._parse_json()
        if rules is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, 'Exportar reglas JSON', 'clasificacion_libros.json', 'JSON (*.json)'
        )
        if not path:
            return
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(rules, f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, 'Exportado', f'Reglas guardadas en:\n{path}')
        except Exception as e:
            QMessageBox.critical(self, 'Error al exportar', str(e))

def show_config_dialog(gui):
    from qt.core import QDialog, QVBoxLayout, QDialogButtonBox
    
    dialog = QDialog(gui)
    dialog.setWindowTitle('Configurar Book Classifier')
    layout = QVBoxLayout(dialog)
    
    widget = ConfigWidget()
    layout.addWidget(widget)
    
    # Botones de Aceptar y Cancelar
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    
    if dialog.exec() == QDialog.DialogCode.Accepted:
        widget.save_settings()