from __future__ import unicode_literals, division, absolute_import, print_function

__license__   = 'GPL v3'
__copyright__ = '2026'

# The class that all Interface Action plugin wrappers must inherit from
from calibre.customize import InterfaceActionBase

class ActionAllLibrariesStats(InterfaceActionBase):
    '''
    Este plugin analiza todos los libros de un autor en todas las librerías de Calibre.
    Para cada autor, informa en qué librería(s) se encuentra y el número total de libros
    del autor sumando todos los de todas las librerías.
    '''
    name                    = 'All Libraries Stats'
    description             = 'Analiza autores en todas las librerías y agrega estadísticas'
    supported_platforms     = ['windows', 'osx', 'linux']
    author                  = 'Yolanda Braojos'
    version                 = (1, 0, 5)
    minimum_calibre_version = (2, 0, 0)

    #: This field defines the GUI plugin class that contains all the code
    #: that actually does something. Its format is module_path:class_name
    #: The specified class must be defined in the specified module.
    actual_plugin           = 'calibre_plugins.all_libraries_stats.action:AllLibrariesStatsAction'

    def is_customizable(self):
        return True

    def config_widget(self):
        if self.actual_plugin_:
            from calibre_plugins.all_libraries_stats.config import ConfigWidget
            return ConfigWidget(self.actual_plugin_)

    def save_settings(self, config_widget):
        config_widget.save_settings()
        if self.actual_plugin_:
            self.actual_plugin_.load_config()


# For testing, run from command line with this:
# calibre-debug -e __init__.py
if __name__ == '__main__':
    try:
        from qt.core import QApplication
    except ImportError:
        from PyQt5.Qt import QApplication
    from calibre.gui2.preferences import test_widget
    app = QApplication([])
    test_widget('Advanced', 'Plugins')
