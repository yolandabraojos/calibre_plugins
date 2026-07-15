from __future__ import unicode_literals, division, absolute_import, print_function

__license__   = 'GPL v3'
__copyright__ = '2024, Extract Metadata Plugin'

# The class that all Interface Action plugin wrappers must inherit from
from calibre.customize import InterfaceActionBase

print("DEBUG: Cargando __init__.py del plugin Extract Metadata...")

class ActionExtractMetadata(InterfaceActionBase):
    '''
    This class is a simple wrapper that provides information about the actual
    plugin class. The actual interface plugin class is called ExtractMetadataAction
    and is defined in the action.py file, as specified in the actual_plugin field
    below.

    The reason for having two classes is that it allows the command line
    calibre utilities to run without needing to load the GUI libraries.
    '''
    name                    = 'Extract Metadata'
    description             = 'Extracts metadata from EPUB and AZW3 files and stores in a custom field'
    supported_platforms     = ['windows', 'osx', 'linux']
    author                  = 'Yolanda Braojos'
    version                 = (1, 3, 2)
    minimum_calibre_version = (2, 0, 0)

    #: This field defines the GUI plugin class that contains all the code
    #: that actually does something. Its format is module_path:class_name
    #: The specified class must be defined in the specified module.
    actual_plugin  = 'calibre_plugins.extract_metadata.action:ExtractMetadataAction'

    def is_customizable(self):
        '''
        This method must return True to enable customization via
        Preferences->Plugins
        '''
        return False

print("DEBUG: __init__.py cargado correctamente.")
