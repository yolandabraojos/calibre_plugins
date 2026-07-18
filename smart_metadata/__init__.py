#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Smart Metadata - calibre interface action plugin
# Descarga metadatos, auto-aplica los que coinciden con alta seguridad
# (titulo y autor identicos o muy similares) y abre la revision manual de
# Calibre (CompareMany) solo con los dudosos.
from __future__ import unicode_literals, division, absolute_import, print_function

__license__ = 'GPL v3'
__copyright__ = '2026, Yolanda Braojos'

from calibre.customize import InterfaceActionBase


class SmartMetadata(InterfaceActionBase):

    name = 'Smart Metadata'
    description = ('Descarga metadatos y portadas, aplica automaticamente los '
                   'que coinciden con alta seguridad (titulo y autor identicos '
                   'o muy similares) y deja para revision manual solo los dudosos.')
    supported_platforms = ['windows', 'osx', 'linux']
    author = 'Yolanda Braojos'
    version = (1, 4, 0)
    minimum_calibre_version = (5, 0, 0)

    actual_plugin = 'calibre_plugins.smart_metadata.ui:SmartMetadataAction'

    def is_customizable(self):
        return True

    def config_widget(self):
        from calibre_plugins.smart_metadata.config import ConfigWidget
        return ConfigWidget()

    def save_settings(self, config_widget):
        config_widget.save_settings()
