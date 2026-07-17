#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Configuracion del plugin Smart Metadata.
from __future__ import unicode_literals, division, absolute_import, print_function

__license__ = 'GPL v3'
__copyright__ = '2026, Yolanda Braojos'

from calibre.utils.config import JSONConfig

try:
    from qt.core import (QWidget, QVBoxLayout, QFormLayout, QLabel, QSpinBox,
                         QCheckBox)
except ImportError:  # Calibre antiguo
    from PyQt5.Qt import (QWidget, QVBoxLayout, QFormLayout, QLabel, QSpinBox,
                          QCheckBox)

# Umbrales en PORCENTAJE (0-100) para que sean comodos en la UI.
prefs = JSONConfig('plugins/smart_metadata')
prefs.defaults['title_threshold'] = 90     # % de similitud de titulo para auto-aceptar
prefs.defaults['author_threshold'] = 80    # % de similitud de autor para auto-aceptar
prefs.defaults['require_author'] = True     # el autor tambien debe superar su umbral


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

    def save_settings(self):
        prefs['title_threshold'] = int(self.title_spin.value())
        prefs['author_threshold'] = int(self.author_spin.value())
        prefs['require_author'] = bool(self.require_author.isChecked())
