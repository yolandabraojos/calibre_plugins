# -*- coding: utf-8 -*-
"""
Calibre Book Classifier Plugin (IA local)
Clasifica libros con un modelo entrenado: sugiere librería y añade tags de tema.
"""

from calibre.customize import InterfaceActionBase


class BookClassifierPlugin(InterfaceActionBase):
    name                    = 'Book Classifier'
    description             = 'Clasifica libros con IA local (librería + tropos) y rescata los no clasificados con un LLM en la nube (opcional)'
    supported_platforms     = ['windows', 'osx', 'linux']
    author                  = 'Yolanda Braojos'
    version                 = (3, 2, 5)
    minimum_calibre_version = (5, 0, 0)

    actual_plugin = 'calibre_plugins.book_classifier.action:BookClassifierAction'

    def is_customizable(self):
        return True

    def config_widget(self):
        from calibre_plugins.book_classifier.config import ConfigWidget
        return ConfigWidget()

    def save_settings(self, config_widget):
        config_widget.save_settings()
