# -*- coding: utf-8 -*-
"""
Calibre Book Classifier Plugin
Clasifica libros automáticamente usando metadatos y un JSON de reglas.
"""

from calibre.customize import InterfaceActionBase

class BookClassifierPlugin(InterfaceActionBase):
    name                    = 'Book Classifier'
    description             = 'Clasifica libros automáticamente basándose en título, subtítulo, comentarios y tags'
    supported_platforms     = ['windows', 'osx', 'linux']
    author                  = 'Yolanda Braojos'
    version                 = (1, 3, 0)
    minimum_calibre_version = (5, 0, 0)

    actual_plugin = 'calibre_plugins.book_classifier.action:BookClassifierAction'

    def is_customizable(self):
        return True

    def config_widget(self):
        from calibre_plugins.book_classifier.config import ConfigWidget
        return ConfigWidget()

    def save_settings(self, config_widget):
        config_widget.save_settings()
