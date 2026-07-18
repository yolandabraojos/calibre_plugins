#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Configuracion del plugin Smart Metadata.
from __future__ import unicode_literals, division, absolute_import, print_function

__license__ = 'GPL v3'
__copyright__ = '2026, Yolanda Braojos'

from calibre.utils.config import JSONConfig

try:
    from qt.core import (QWidget, QVBoxLayout, QFormLayout, QLabel, QSpinBox,
                         QCheckBox, QLineEdit)
except ImportError:  # Calibre antiguo
    from PyQt5.Qt import (QWidget, QVBoxLayout, QFormLayout, QLabel, QSpinBox,
                          QCheckBox, QLineEdit)

# Umbrales en PORCENTAJE (0-100) para que sean comodos en la UI.
prefs = JSONConfig('plugins/smart_metadata')
prefs.defaults['title_threshold'] = 90     # % de similitud de titulo para auto-aceptar
prefs.defaults['author_threshold'] = 80    # % de similitud de autor para auto-aceptar
prefs.defaults['require_author'] = True     # el autor tambien debe superar su umbral
prefs.defaults['batch_size'] = 25           # procesar en rondas de N libros (0 = todos de una vez)
prefs.defaults['use_fallback'] = True       # reintentar los fallidos con otro campo de titulo
prefs.defaults['fallback_field'] = '#title_opf'  # lookup del campo de titulo alternativo


class ConfigWidget(QWidget):

    def __init__(self):
        QWidget.__init__(self)
        root = QVBoxLayout(self)

        intro = QLabel(
            'Un libro se aplica AUTOMATICAMENTE (sin revision) cuando su '
            'similitud de titulo\n'
            '-y opcionalmente de autor- con el libro original supera estos '
            'umbrales.\n'
            'Los que no lleguen se abren en la revision manual de Calibre.')
        intro.setWordWrap(True)
        root.addWidget(intro)

        form = QFormLayout()
        root.addLayout(form)

        self.title_spin = QSpinBox(self)
        self.title_spin.setRange(0, 100)
        self.title_spin.setSuffix(' %')
        self.title_spin.setValue(int(prefs['title_threshold']))
        form.addRow('Umbral de titulo:', self.title_spin)

        self.require_author = QCheckBox(
            'Exigir tambien coincidencia de autor', self)
        self.require_author.setChecked(bool(prefs['require_author']))
        form.addRow('', self.require_author)

        self.author_spin = QSpinBox(self)
        self.author_spin.setRange(0, 100)
        self.author_spin.setSuffix(' %')
        self.author_spin.setValue(int(prefs['author_threshold']))
        form.addRow('Umbral de autor:', self.author_spin)

        self.require_author.toggled.connect(self.author_spin.setEnabled)
        self.author_spin.setEnabled(self.require_author.isChecked())

        self.batch_spin = QSpinBox(self)
        self.batch_spin.setRange(0, 2000)
        self.batch_spin.setSuffix(' libros')
        self.batch_spin.setSpecialValueText('Todos de una vez')  # se muestra cuando vale 0
        self.batch_spin.setValue(int(prefs['batch_size']))
        form.addRow('Procesar en rondas de:', self.batch_spin)

        note = QLabel(
            'Con selecciones grandes, procesar en rondas mantiene cada revision '
            'acotada y va aplicando lo seguro ronda a ronda. 0 = una sola tanda.')
        note.setWordWrap(True)
        root.addWidget(note)

        self.use_fallback = QCheckBox(
            'Reintentar los libros no encontrados usando otro campo de titulo',
            self)
        self.use_fallback.setChecked(bool(prefs['use_fallback']))
        form.addRow('', self.use_fallback)

        self.fallback_field = QLineEdit(self)
        self.fallback_field.setText(str(prefs['fallback_field'] or ''))
        self.fallback_field.setPlaceholderText('#title_opf')
        form.addRow('Campo de titulo alternativo:', self.fallback_field)

        self.use_fallback.toggled.connect(self.fallback_field.setEnabled)
        self.fallback_field.setEnabled(self.use_fallback.isChecked())

        note2 = QLabel(
            'Fallback: si un libro no encuentra nada con su titulo de '
            'biblioteca, se reintenta la busqueda con el titulo de este campo '
            '(p.ej. la columna personalizada #title_opf). Util cuando el titulo '
            'de la biblioteca viene sucio del nombre de fichero.')
        note2.setWordWrap(True)
        root.addWidget(note2)

    def save_settings(self):
        prefs['title_threshold'] = int(self.title_spin.value())
        prefs['author_threshold'] = int(self.author_spin.value())
        prefs['require_author'] = bool(self.require_author.isChecked())
        prefs['batch_size'] = int(self.batch_spin.value())
        prefs['use_fallback'] = bool(self.use_fallback.isChecked())
        prefs['fallback_field'] = str(self.fallback_field.text()).strip() or '#title_opf'
