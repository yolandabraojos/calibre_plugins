from calibre.customize import InterfaceActionBase


class EbookComparatorPlugin(InterfaceActionBase):
    name                    = 'Ebook Comparator'
    description             = 'Compara ebooks y muestra porcentaje de similitud'
    supported_platforms     = ['windows', 'osx', 'linux']
    author                  = 'Yolanda Braojos'
    version                 = (2, 5, 0)
    minimum_calibre_version = (6, 0, 0)
    actual_plugin           = 'calibre_plugins.ebook_comparator.action:EbookComparatorAction'
    icon = 'plugin.svg'

    def is_customizable(self):
        return True
