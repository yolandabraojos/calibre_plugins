from __future__ import unicode_literals, division, absolute_import, print_function

__license__   = 'GPL v3'
__copyright__ = '2026, Fix Metadata Plugin'

from calibre.customize import InterfaceActionBase


class ActionFixMetadata(InterfaceActionBase):
    '''
    Wrapper class for the Fix Metadata plugin.
    The actual GUI class is FixMetadataAction defined in action.py.
    '''
    name                    = 'Fix Metadata'
    description             = ('Extracts metadata from EPUB/AZW3 files, cleans '
                                'series prefixes from titles and normalises author names')
    supported_platforms     = ['windows', 'osx', 'linux']
    author                  = 'Yolanda Braojos'
    version                 = (1, 3, 3)
    minimum_calibre_version = (2, 0, 0)

    actual_plugin = 'calibre_plugins.fix_metadata.action:FixMetadataAction'

    def is_customizable(self):
        return False
