import os, sqlite3, re
from collections import defaultdict

class LibraryAnalyzer:

    @staticmethod
    def find_libraries(libraries_path):
        libraries = []
        if not os.path.exists(libraries_path): return libraries
        try:
            for item in os.listdir(libraries_path):
                path = os.path.join(libraries_path, item)
                if os.path.isdir(path) and os.path.isfile(os.path.join(path, 'metadata.db')):
                    libraries.append((item, path))
        except: pass
        return libraries

    @staticmethod
    def batch_iterator(iterable, batch_size=100):
        for i in range(0, len(iterable), batch_size):
            yield iterable[i:i + batch_size]

    @staticmethod
    def normalize_title(title):
        if not title: return ""
        t = title.lower()
        t = re.sub(r'[\(\[].*?[\)\]]', '', t)
        t = re.sub(r'(\s*-\s*)?\b(spa|eng|esp|fans)\b(\s*-\s*fans)?$', '', t)
        if ' - ' in t: t = t.split(' - ')[-1]
        t = re.sub(r'[^\w\s]', '', t)
        return re.sub(r'\s+', ' ', t).strip()

    @staticmethod
    def collect_author_stats(libraries, log_func=None):
        if log_func: log_func("[DEBUG-ALS] [ANALYZER] Iniciando collect_author_stats...")
        stats = defaultdict(lambda: defaultdict(int))
        for name, path in libraries:
            db_path = os.path.join(path, 'metadata.db')
            try:
                conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=20)
                cursor = conn.cursor()
                cursor.execute('SELECT a.name, COUNT(bl.book) FROM authors a JOIN books_authors_link bl ON a.id = bl.author GROUP BY a.name')
                for row in cursor.fetchall(): stats[row[0]][name] = row[1]
                conn.close()
            except Exception as e:
                if log_func: log_func(f"[DEBUG-ALS] [ANALYZER] Error leyendo {name}: {e}")
                
        for a in stats: stats[a]['total'] = sum(stats[a].values())
        return stats

    @staticmethod
    def collect_title_stats(libraries, log_func=None):
        if log_func: log_func("[DEBUG-ALS] [ANALYZER] Iniciando collect_title_stats...")
        title_stats = defaultdict(set)
        for name, path in libraries:
            db_path = os.path.join(path, 'metadata.db')
            try:
                conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=20)
                cursor = conn.cursor()
                cursor.execute('SELECT b.title, a.name FROM books b JOIN books_authors_link bl ON b.id = bl.book JOIN authors a ON bl.author = a.id')
                for title, author in cursor.fetchall():
                    title_stats[(LibraryAnalyzer.normalize_title(title), author)].add(name)
                conn.close()
            except Exception as e:
                if log_func: log_func(f"[DEBUG-ALS] [ANALYZER] Error leyendo títulos en {name}: {e}")
        return title_stats

    @staticmethod
    def calculate_metadata_updates(books_data, field_meta, author_stats, title_stats, batch, current_library_name=""):
        lib_updates, total_updates, dup_updates = {}, {}, {}

        fm_lib = field_meta.get('lib', {})
        fm_tot = field_meta.get('tot', {})
        fm_dup = field_meta.get('dup', {})

        if not (fm_lib or fm_tot or fm_dup):
            return lib_updates, total_updates, dup_updates

        for bid in batch:
            b_info = books_data.get(bid)
            if not b_info: continue
            
            authors = b_info['authors']
            if not authors: continue

            title = b_info['title']
            norm_title = LibraryAnalyzer.normalize_title(title)

            found_libs, max_total = set(), 0

            for a in authors:
                if a in author_stats:
                    found_libs.update([k for k in author_stats[a] if k != 'total'])
                    max_total = max(max_total, author_stats[a]['total'])

            # --- LIBRERÍAS DE AUTOR (Filtramos la librería actual) ---
            if fm_lib:
                found_libs.discard(current_library_name) # <- ELIMINA LA LIBRERÍA ACTUAL
                if found_libs:
                    lib_updates[bid] = sorted(list(found_libs)) if fm_lib.get('is_multiple') else ', '.join(sorted(found_libs))
                else:
                    lib_updates[bid] = [] if fm_lib.get('is_multiple') else ''

            # --- TOTAL DE LIBROS ---
            if fm_tot and max_total > 0:
                total_updates[bid] = max_total if fm_tot.get('datatype') in ['int', 'float'] else str(max_total)

            # --- DUPLICADOS (Filtramos la librería actual) ---
            if fm_dup:
                d_libs = set()
                for a in authors:
                    if (norm_title, a) in title_stats: 
                        d_libs.update(title_stats[(norm_title, a)])
                
                d_libs.discard(current_library_name) # <- ELIMINA LA LIBRERÍA ACTUAL
                if d_libs:
                    count = len(d_libs)
                    dup_updates[bid] = sorted(list(d_libs)) if fm_dup.get('is_multiple') else f"{count}: {', '.join(sorted(d_libs))}"
                else:
                    dup_updates[bid] = [] if fm_dup.get('is_multiple') else ''

        return lib_updates, total_updates, dup_updates