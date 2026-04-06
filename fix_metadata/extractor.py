from __future__ import unicode_literals, division, absolute_import, print_function

__license__   = 'GPL v3'
__copyright__ = '2024, Extract Metadata Plugin'

import re
import os
import tempfile
import shutil
import html
import zipfile
import logging
import sys
from xml.etree import ElementTree as ET

# Configuración robusta para Calibre
logger = logging.getLogger('EXTRACTOR_PLUGIN')

# Si el logger no tiene manejadores, le añadimos uno que escriba en la consola
if not logger.handlers:
    # Redigimos a stdout para que aparezca en el terminal de Calibre
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    logger.setLevel(logging.DEBUG)

# Evitar que los mensajes se dupliquen si Calibre ya tiene un logger raíz
logger.propagate = False

def extract_metadata(file_path, file_format):
    '''
    Función principal con trazabilidad completa para el debug de Calibre.
    '''
    file_format = file_format.upper()
    logger.info(f"--- Iniciando extracción de metadatos ---")
    logger.info(f"Formato detectado: {file_format}")
    logger.info(f"Ruta: {file_path}")
    
    result = (None, None, None, [])
    
    try:
        if file_format == 'EPUB':
            result = extract_metadata_from_epub(file_path)
        elif file_format == 'AZW3':
            result = extract_metadata_from_azw3(file_path)
        else:
            logger.warning(f"Formato '{file_format}' no es soportado por este extractor.")
            
        logger.info(f"Extracción finalizada. Resultado: Gen='{result[0]}', Prod='{result[1]}', Título='{result[2]}'")
    except Exception as e:
        logger.error(f"Error crítico en la función principal: {str(e)}", exc_info=True)
 
    return result

def extract_metadata_from_epub(epub_path):
    '''Extrae metadatos de un EPUB buscando y analizando su OPF internamente.'''
    logger.debug(f"Abriendo archivo EPUB: {os.path.basename(epub_path)}")
    try:
        with zipfile.ZipFile(epub_path, 'r') as epub_zip:
            opf_path = None
            
            # Intento 1: Buscar vía container.xml
            try:
                container_xml = epub_zip.read('META-INF/container.xml')
                root = ET.fromstring(container_xml)
                ns = {'container': 'urn:oasis:names:tc:opendocument:xmlns:container'}
                rootfile = root.find('.//container:rootfile', ns)
                if rootfile is not None:
                    opf_path = rootfile.get('full-path')
                    logger.debug(f"OPF localizado vía container.xml: {opf_path}")
            except Exception as e:
                logger.debug(f"No se pudo leer container.xml: {str(e)}")

            # Intento 2: Búsqueda directa de cualquier .opf
            if not opf_path:
                logger.debug("Buscando archivos .opf manualmente en el ZIP...")
                for file_name in epub_zip.namelist():
                    if file_name.lower().endswith('.opf'):
                        opf_path = file_name
                        logger.debug(f"OPF localizado por extensión: {opf_path}")
                        break
            
            if opf_path and opf_path in epub_zip.namelist():
                opf_content = epub_zip.read(opf_path)
                return extract_metadata_from_opf(opf_content)
            else:
                logger.error("No se encontró ningún archivo OPF dentro del EPUB.")
                
    except Exception as e:
        logger.error(f"Error al procesar el ZIP del EPUB: {str(e)}")
        
    return (None, None, None, [])

def extract_metadata_from_azw3(file_path):
    generator, producer, title_opf = None, None, None
    subjects = [] # Inicializamos lista de temas
    
    file_path = os.path.abspath(file_path)
    original_cwd = os.getcwd()
    tdir = tempfile.mkdtemp(prefix='kf8_extract_')
    
    logger.info("=" * 70)
    logger.info("EXTRACCIÓN DE METADATOS DESDE AZW3")
    logger.info("=" * 70)
    logger.info(f"Ruta del archivo: {file_path}")
    logger.info(f"Directorio temporal: {tdir}")
    
    try:
        from calibre.ebooks.mobi.reader.mobi6 import MobiReader
        from calibre.ebooks.mobi.reader.mobi8 import Mobi8Reader
        from calibre.ebooks.metadata.mobi import get_metadata
        
        with open(file_path, 'rb') as f:
            # 1. Metadatos rápidos
            logger.info("\n--- Fase 1: Lectura rápida de metadatos con get_metadata ---")
            try:
                mi = get_metadata(f)
                title_opf = getattr(mi, 'title', None)
                if title_opf:
                    logger.info(f"✓ Título encontrado: {title_opf}")
                else:
                    logger.debug("✗ Título no encontrado en get_metadata")
                    
                if hasattr(mi, 'tags'):
                    subjects = mi.tags
                    logger.info(f"✓ Temas encontrados en get_metadata: {len(subjects)} items")
                else:
                    logger.debug("✗ Tags no encontrados en get_metadata")
            except Exception as e:
                logger.debug(f"⚠ Error en get_metadata: {str(e)}")
            
            f.seek(0)
            logger.info("\n--- Fase 2: Lectura de estructura MOBI con MobiReader ---")
            mr = MobiReader(f)
            logger.info(f"Tipo KF8: {mr.kf8_type}")
            
            if mr.kf8_type is not None:
                logger.info("✓ Es un archivo KF8 (AZW3), procediendo a descompilación...")
                os.chdir(tdir)
                reader8 = Mobi8Reader(mr, logger)
                
                try:
                    # Ejecutamos el descompilador
                    logger.info("\n--- Fase 3: Descompilación de KF8 ---")
                    opf_filename = reader8()
                    logger.info(f"Archivo OPF generado: {opf_filename}")
                    
                    if os.path.exists(opf_filename):
                        logger.info(f"✓ Archivo OPF existe, leyendo contenido...")
                        with open(opf_filename, 'rb') as f_opf:
                            opf_content = f_opf.read().decode('utf-8', errors='ignore')
                            logger.info(f"✓ Contenido OPF leído ({len(opf_content)} caracteres)")
                            
                            # Extraemos datos del OPF
                            logger.info("\n--- Fase 4: Análisis del OPF descompilado ---")
                            g, p, t, s = extract_metadata_from_opf(opf_content)
                            generator, producer = g, p
                            if not title_opf: 
                                title_opf = t
                            
                            # Si no obtuvimos subjects de get_metadata, probamos con el OPF
                            if not subjects:
                                subjects = s
                                if subjects:
                                    logger.info(f"✓ Temas obtenidos del OPF: {len(subjects)} items")
                    else:
                        logger.error(f"✗ Archivo OPF no existe en: {opf_filename}")
                        
                except Exception as e:
                    logger.error(f"✗ Error en Mobi8Reader: {str(e)}", exc_info=True)

                # 3. FALLBACK EXTH (para Generator, Producer y Subjects)
                logger.info("\n--- Fase 5: Búsqueda en registros EXTH como fallback ---")
                exth8 = getattr(reader8, 'exth_mobi8', None)
                if exth8:
                    logger.debug("✓ EXTH8 disponible")
                    if not generator:
                        gen_bytes = exth8.get_record(535)
                        if gen_bytes: 
                            generator = gen_bytes.decode('utf-8', errors='ignore')
                            logger.info(f"✓ Generador encontrado en EXTH (535): {generator}")
                    
                    if not producer:
                        prod_bytes = exth8.get_record(204)
                        if prod_bytes: 
                            producer = prod_bytes.decode('utf-8', errors='ignore')
                            logger.info(f"✓ Productor encontrado en EXTH (204): {producer}")

                    if not subjects:
                        # El código 105 es el estándar para 'Subject' o 'Keywords'
                        sub_bytes = exth8.get_record(105)
                        if sub_bytes:
                            raw_subjects = sub_bytes.decode('utf-8', errors='ignore')
                            # A veces vienen separados por comas en un solo registro
                            subjects = [s.strip() for s in raw_subjects.split(',') if s.strip()]
                            logger.info(f"✓ Temas encontrados en EXTH (105): {len(subjects)} items")
                else:
                    logger.debug("✗ EXTH8 no disponible")
            else:
                logger.warning("✗ No es un archivo KF8, es MOBI antiguo o formato inválido")

    except Exception as e:
        logger.error(f"✗ Error crítico en extract_metadata_from_azw3: {str(e)}", exc_info=True)
    finally:
        os.chdir(original_cwd)
        if os.path.exists(tdir):
            shutil.rmtree(tdir, ignore_errors=True)
        logger.info("\n--- Limpieza completada ---")
        
    logger.info("\n" + "=" * 70)
    logger.info("RESUMEN FINAL DE EXTRACCIÓN AZW3")
    logger.info("=" * 70)
    logger.info(f"Generador: {'✓ ' + generator if generator else '✗ No encontrado'}")
    logger.info(f"Productor: {'✓ ' + producer if producer else '✗ No encontrado'}")
    logger.info(f"Título: {'✓ ' + title_opf if title_opf else '✗ No encontrado'}")
    logger.info(f"Temas: {len(subjects)} encontrados")
    logger.info("=" * 70)
        
    return (generator, producer, title_opf, subjects)

def extract_metadata_from_opf(opf_content):
    '''Coordina la extracción de los tres campos desde el XML del OPF.'''
    if isinstance(opf_content, bytes):
        opf_content = opf_content.decode('utf-8', errors='ignore')
    
    logger.info("=" * 70)
    logger.info("INICIANDO ANÁLISIS DEL ARCHIVO OPF")
    logger.info("=" * 70)
    logger.debug(f"Tamaño del contenido OPF: {len(opf_content)} caracteres")
    
    # Log del inicio del OPF para verificar estructura
    logger.debug(f"Primeros 500 caracteres del OPF:\n{opf_content[:500]}")
    
    # Búsqueda de etiquetas importantes
    logger.debug("\n--- Búsqueda de etiquetas críticas ---")
    if '<metadata>' in opf_content.lower():
        logger.debug("✓ Se encontró sección <metadata>")
    else:
        logger.debug("✗ NO se encontró sección <metadata>")
    
    # Contador de dc: tags encontrados
    dc_tags = re.findall(r'<dc:\w+[^>]*>', opf_content)
    logger.debug(f"Total de etiquetas dc: (Dublin Core) encontradas: {len(dc_tags)}")
    
    book_producer = extract_book_producer_from_opf(opf_content)
    generator = extract_generator_tag_from_opf(opf_content)
    title_opf = extract_title_from_opf(opf_content)
    subjects = extract_subjects_from_opf(opf_content)
    
    # Resumen final
    logger.info("\n--- RESUMEN DE EXTRACCIÓN ---")
    logger.info(f"Título OPF: {'✓ ' + title_opf if title_opf else '✗ No encontrado'}")
    logger.info(f"Generador: {'✓ ' + generator if generator else '✗ No encontrado'}")
    logger.info(f"Productor: {'✓ ' + book_producer if book_producer else '✗ No encontrado'}")
    logger.info(f"Temas: {len(subjects)} encontrados" + (f" {subjects}" if subjects else ""))
    logger.info("=" * 70)
    
    return (generator, book_producer, title_opf, subjects)

def extract_book_producer_from_opf(opf_content):
    """
    Busca <dc:contributor> con opf:role="bkp" en el OPF.
    Con trazabilidad completa para debugging.
    """
    logger.debug("=" * 60)
    logger.debug("BÚSQUEDA DE PRODUCTOR (dc:contributor con role='bkp')")
    logger.debug("=" * 60)
    
    # Primero, vamos a inspeccionar todo lo que hay con dc:contributor
    all_contributors = re.findall(r'<dc:contributor[^>]*>[^<]*</dc:contributor>', opf_content, re.IGNORECASE | re.DOTALL)
    logger.debug(f"Total de <dc:contributor> encontrados: {len(all_contributors)}")
    for i, contrib in enumerate(all_contributors):
        logger.debug(f"  [{i+1}] {contrib[:150]}...")
    
    # Búsqueda específica con diferentes patrones, con logs
    patterns = [
        # Patrón 1: role="bkp" antes del contenido (clásico)
        (r'<dc:contributor[^>]*opf:role=["\']bkp["\'][^>]*>([^<]+)</dc:contributor>', 
         "Patrón 1: role='bkp' antes del contenido"),
        
        # Patrón 2: role="bkp" después de otras atributos
        (r'<dc:contributor[^>]*>([^<]*)</dc:contributor>(?=.*opf:role=["\']bkp["\'])',
         "Patrón 2: búsqueda lookahead"),
        
        # Patrón 3: Búsqueda más flexible con atributos variados
        (r'<dc:contributor\s+[^>]*opf:role=["\']bkp["\'][^>]*>([^<]+)</dc:contributor>',
         "Patrón 3: con espacios en blanco explícitos"),
        
        # Patrón 4: Búsqueda con file-as también presente
        (r'<dc:contributor\s+[^>]*opf:role=["\']bkp["\'][^>]*opf:file-as=["\']([^"\']+)["\'][^>]*>([^<]+)</dc:contributor>',
         "Patrón 4: capturando file-as"),
    ]
    
    for pattern, description in patterns:
        logger.debug(f"\nIntentando: {description}")
        logger.debug(f"  Regex: {pattern[:80]}...")
        match = re.search(pattern, opf_content, re.IGNORECASE | re.DOTALL)
        if match:
            result = match.group(1).strip()
            logger.info(f"  ✓ ENCONTRADO: {result}")
            return result
        else:
            logger.debug(f"  ✗ Sin coincidencias")
    
    # Patrón 5: Búsqueda más agresiva - cualquier dc:contributor con role="bkp"
    logger.debug(f"\nIntentando: Patrón 5: búsqueda con role='bkp' en toda la etiqueta")
    # Buscar la etiqueta completa que contiene role="bkp"
    bkp_tags = re.findall(r'<dc:contributor[^>]*opf:role=["\']bkp["\'][^>]*>([^<]+)</dc:contributor>', 
                          opf_content, re.IGNORECASE | re.DOTALL)
    if bkp_tags:
        for tag in bkp_tags:
            logger.info(f"  ✓ ENCONTRADO (búsqueda agresiva): {tag.strip()}")
            return bkp_tags[0].strip()
    
    # Patrón 6: Último recurso - parsear con ElementTree
    logger.debug(f"\nIntentando: Patrón 6: parseador XML ElementTree")
    try:
        if isinstance(opf_content, str):
            opf_bytes = opf_content.encode('utf-8')
        else:
            opf_bytes = opf_content
            
        root = ET.fromstring(opf_bytes)
        
        # Buscar todos los namespaces
        namespaces = {
            'dc': 'http://purl.org/dc/elements/1.1/',
            'opf': 'http://www.idpf.org/2007/opf',
            '': ''
        }
        
        # Intentar buscar con diferentes combinaciones de namespace
        for contrib in root.iter():
            if 'contributor' in contrib.tag.lower():
                logger.debug(f"  Encontrado tag: {contrib.tag}")
                logger.debug(f"    Atributos: {contrib.attrib}")
                
                # Buscar el atributo role (con namespace opf)
                role = contrib.get('{http://www.idpf.org/2007/opf}role') or contrib.get('role')
                logger.debug(f"    Role extraído: {role}")
                
                if role == 'bkp':
                    result = contrib.text.strip() if contrib.text else None
                    if result:
                        logger.info(f"  ✓ ENCONTRADO (ElementTree): {result}")
                        return result
    except Exception as e:
        logger.debug(f"  ✗ Error en ElementTree: {str(e)}")
    
    logger.warning("No se encontró <dc:contributor> con role='bkp'")
    logger.debug("=" * 60)
    return None

def extract_generator_tag_from_opf(opf_content):
    # 1. Regex meta generator
    gen_patterns = [
        r'<meta[^>]*name=["\']generator["\'][^>]*content=["\']([^"\']+)["\']',
        r'<meta[^>]*content=["\']([^"\']+)["\'][^>]*name=["\']generator["\']'
    ]
    for p in gen_patterns:
        match = re.search(p, opf_content, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
    
    # 2. Regex para Sigil
    sigil_patterns = [
        r'<meta[^>]*name=["\']Sigil version["\'][^>]*content=["\']([^"\']+)["\']',
        r'<meta[^>]*content=["\']([^"\']+)["\'][^>]*name=["\']Sigil version["\']'
    ]
    for p in sigil_patterns:
        match = re.search(p, opf_content, re.IGNORECASE | re.DOTALL)
        if match:
            return "Sigil " + match.group(1).strip()

    # 3. Fallback con ElementTree
    try:
        # Eliminamos posibles declaraciones de encoding que rompan el ET.fromstring si es un string
        # o nos aseguramos de que sea bytes
        if isinstance(opf_content, str):
            opf_content = opf_content.encode('utf-8')
            
        root = ET.fromstring(opf_content)
        # Buscamos todos los meta, sin importar el namespace
        for meta in root.iter():
            if 'meta' in meta.tag:
                name = (meta.get('name') or '').lower()
                content = meta.get('content')
                if name == 'generator':
                    return content
                if name == 'sigil version':
                    return f"Sigil {content}"
    except Exception as e:
        logger.debug(f"Error parseando XML: {e}")
        pass
    return None

def extract_title_from_opf(opf_content):
    '''Extrae el contenido de la etiqueta <dc:title> con traza de respaldo.'''
    match = re.search(r'<dc:title[^>]*>([^<]+)</dc:title>', opf_content, re.IGNORECASE | re.DOTALL)
    if match:
        return html.unescape(match.group(1).strip())
    
    try:
        root = ET.fromstring(opf_content.encode('utf-8'))
        ns = {'dc': 'http://purl.org/dc/elements/1.1/'}
        title_tag = root.find('.//dc:title', ns)
        if title_tag is not None:
            return html.unescape(title_tag.text.strip())
    except Exception:
        logger.debug("Fallo al parsear XML para extraer el título.")
        
    return None

def extract_subjects_from_opf(opf_content):
    """Busca todas las ocurrencias de <dc:subject> y devuelve una lista."""
    subjects = re.findall(r'<dc:subject[^>]*>([^<]+)</dc:subject>', opf_content, re.IGNORECASE | re.DOTALL)
    # Limpiamos espacios y eliminamos duplicados
    return [html.unescape(s.strip()) for s in subjects if s.strip()]