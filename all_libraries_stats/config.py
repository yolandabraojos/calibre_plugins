from __future__ import unicode_literals, division, absolute_import, print_function

__license__ = 'GPL v3'

import six, copy
import os
from six import text_type as unicode

try:
    from qt.core import (QWidget, QVBoxLayout, QLabel, QPushButton, QGroupBox, QGridLayout, 
                         QLineEdit, QFileDialog, QMessageBox, QTextEdit, QComboBox)
except ImportError:
    from PyQt5.Qt import (QWidget, QVBoxLayout, QLabel, QPushButton, QGroupBox, QGridLayout, 
                          QLineEdit, QFileDialog, QMessageBox, QTextEdit, QComboBox)

# Simple translation function
def _(s):
    return s

KEY_LIBRARIES_PATH = 'libraries_path'
KEY_LIBRARY_FIELD = 'library_field'
KEY_TOTAL_BOOKS_FIELD = 'total_books_field'
KEY_DUPLICATE_TITLES_FIELD = 'duplicate_titles_field'

DEFAULT_LIBRARY_VALUES = {
    KEY_LIBRARIES_PATH: '',
    KEY_LIBRARY_FIELD: '#author_libraries',
    KEY_TOTAL_BOOKS_FIELD: '#author_total_books',
    KEY_DUPLICATE_TITLES_FIELD: '#duplicate_titles'
}

PREFS_NAMESPACE = 'AllLibrariesStats'
PREFS_KEY_SETTINGS = 'settings'


def get_library_config(db):
    """Obtiene configuración de la librería."""
    library_config = db.prefs.get_namespaced(
        PREFS_NAMESPACE, 
        PREFS_KEY_SETTINGS, 
        copy.deepcopy(DEFAULT_LIBRARY_VALUES)
    )
    return library_config


def set_library_config(db, library_config):
    """Guarda configuración de la librería."""
    db.prefs.set_namespaced(PREFS_NAMESPACE, PREFS_KEY_SETTINGS, library_config)


class ConfigWidget(QWidget):
    """Widget de configuración del plugin."""

    def __init__(self, plugin_action):
        QWidget.__init__(self)
        self.plugin_action = plugin_action
        self.library_config = get_library_config(plugin_action.gui.current_db)
        layout = QVBoxLayout(self)
        self.setLayout(layout)

        # Grupo de opciones
        group_box = QGroupBox(_('Configuración de análisis:'), self)
        layout.addWidget(group_box)
        group_box_layout = QGridLayout()
        group_box.setLayout(group_box_layout)

        # Rutas de librerías (múltiples)
        libraries_path = self.library_config.get(
            KEY_LIBRARIES_PATH, 
            DEFAULT_LIBRARY_VALUES[KEY_LIBRARIES_PATH]
        )
        
        libraries_label = QLabel(_('Rutas padre de librerías:'), self)
        self.libraries_text = QTextEdit(self)
        self.libraries_text.setPlainText(libraries_path)
        self.libraries_text.setToolTip(
            _('Rutas del directorio padre que contienen librerías de Calibre.\n'
              'Una ruta por línea. Ejemplo:\n'
              'C:\\Calibre Library\n'
              'D:\\Mis Librerías\n'
              '/home/user/calibre_libraries')
        )
        self.libraries_text.setMaximumHeight(120)
        libraries_button = QPushButton(_('Añadir ruta...'), self)
        libraries_button.clicked.connect(self.add_libraries_path)

        group_box_layout.addWidget(libraries_label, 0, 0, 1, 3)
        group_box_layout.addWidget(self.libraries_text, 1, 0, 1, 3)
        group_box_layout.addWidget(libraries_button, 2, 2)

        # Campo para librería
        library_field = self.library_config.get(
            KEY_LIBRARY_FIELD, 
            DEFAULT_LIBRARY_VALUES[KEY_LIBRARY_FIELD]
        )
        
        library_label = QLabel(_('Campo para librería:'), self)
        self.library_line = QLineEdit(library_field, self)
        self.library_line.setToolTip(
            _('Nombre del campo personalizado donde guardar el nombre de la librería.\n'
              'Ejemplo: #library\n'
              'Tipo recomendado: "Texto (una sola línea)"')
        )
        
        group_box_layout.addWidget(library_label, 3, 0)
        group_box_layout.addWidget(self.library_line, 3, 1, 1, 2)

        # Campo para total de libros
        total_books_field = self.library_config.get(
            KEY_TOTAL_BOOKS_FIELD, 
            DEFAULT_LIBRARY_VALUES[KEY_TOTAL_BOOKS_FIELD]
        )
        
        total_label = QLabel(_('Campo para total de libros:'), self)
        self.total_line = QLineEdit(total_books_field, self)
        self.total_line.setToolTip(
            _('Nombre del campo personalizado donde guardar el total de libros del autor.\n'
              'Ejemplo: #total_books\n'
              'Tipo recomendado: "Número" o "Número con decimales"')
        )
        
        group_box_layout.addWidget(total_label, 4, 0)
        group_box_layout.addWidget(self.total_line, 4, 1, 1, 2)

        # Campo para títulos duplicados (librerías donde se encuentra el título)
        duplicate_titles_field = self.library_config.get(
            KEY_DUPLICATE_TITLES_FIELD, 
            DEFAULT_LIBRARY_VALUES[KEY_DUPLICATE_TITLES_FIELD]
        )
        
        duplicate_label = QLabel(_('Campo para información de duplicados:'), self)
        self.duplicate_line = QLineEdit(duplicate_titles_field, self)
        self.duplicate_line.setToolTip(
            _('Nombre del campo personalizado donde guardar el número de librerías y las librerías donde se encuentra el título.\n'
              'Ejemplo: #duplicate_info\n'
              'Tipo recomendado: "Texto (una sola línea)"\n'
              'Útil para detectar títulos duplicados en diferentes librerías')
        )
        
        group_box_layout.addWidget(duplicate_label, 5, 0)
        group_box_layout.addWidget(self.duplicate_line, 5, 1, 1, 2)

        # Información adicional
        info_box = QGroupBox(_('Información:'), self)
        layout.addWidget(info_box)
        info_layout = QVBoxLayout()
        info_box.setLayout(info_layout)
        
        info_text = QTextEdit(self)
        info_text.setReadOnly(True)
        info_text.setText(
            _('Este plugin analiza todos los libros en todas las librerías configuradas.\n\n'
              'Para cada autor:\n'
              '1. Busca en qué librería(s) tiene libros\n'
              '2. Cuenta el total de libros del autor sumando todas las librerías\n'
              '3. Actualiza los campos configurados en el formulario del libro\n\n'
              'El campo de duplicados incluye el número de librerías donde aparece el título y la lista de esas librerías.\n\n'
              'Es necesario crear los campos personalizados en Calibre antes de '
              'ejecutar este plugin.')
        )
        info_text.setMaximumHeight(120)
        info_layout.addWidget(info_text)

    def add_libraries_path(self):
        """Abre un diálogo para seleccionar y añadir rutas de librerías."""
        path = QFileDialog.getExistingDirectory(
            self,
            _('Seleccionar ruta padre de librerías')
        )
        if path:
            current_text = self.libraries_text.toPlainText().strip()
            if current_text:
                self.libraries_text.setPlainText(current_text + '\n' + path)
            else:
                self.libraries_text.setPlainText(path)

    def save_settings(self):
        """Guarda la configuración."""
        self.library_config[KEY_LIBRARIES_PATH] = self.libraries_text.toPlainText()
        self.library_config[KEY_LIBRARY_FIELD] = self.library_line.text()
        self.library_config[KEY_TOTAL_BOOKS_FIELD] = self.total_line.text()
        self.library_config[KEY_DUPLICATE_TITLES_FIELD] = self.duplicate_line.text()
        
        set_library_config(self.plugin_action.gui.current_db, self.library_config)

    def validate(self):
        """Valida la configuración."""
        lib_paths = self.libraries_text.toPlainText().strip().split('\n')
        lib_field = self.library_line.text().strip()
        total_field = self.total_line.text().strip()
        duplicate_field = self.duplicate_line.text().strip()

        # Limpiar rutas vacías
        lib_paths = [p.strip() for p in lib_paths if p.strip()]

        if not lib_paths:
            QMessageBox.warning(
                self,
                _('Validación'),
                _('Por favor, especifica al menos una ruta padre de librerías.')
            )
            return False

        # Validar que todas las rutas existen
        for lib_path in lib_paths:
            if not os.path.isdir(lib_path):
                QMessageBox.warning(
                    self,
                    _('Validación'),
                    _('La ruta especificada no existe: {}').format(lib_path)
                )
                return False

        if not lib_field:
            QMessageBox.warning(
                self,
                _('Validación'),
                _('Por favor, especifica el nombre del campo para la librería.')
            )
            return False

        if not total_field:
            QMessageBox.warning(
                self,
                _('Validación'),
                _('Por favor, especifica el nombre del campo para el total de libros.')
            )
            return False

        if not duplicate_field:
            QMessageBox.warning(
                self,
                _('Validación'),
                _('Por favor, especifica el nombre del campo para la información de duplicados.')
            )
            return False

        return True

    def select_patterns_file(self):
        """Abre un diálogo para seleccionar el archivo de patrones."""
        current_path = self.patterns_line.text()
        path, _ = QFileDialog.getOpenFileName(
            self,
            _('Seleccionar archivo de patrones JSON'),
            current_path,
            _('JSON files (*.json)')
        )
        if path:
            self.patterns_line.setText(path)
