---
name: fix-comments-extra-sections
description: "Al revisar comments en fix_metadata, chequear también secciones About the Author/Praise/Reviews/Excerpt; el HTML no es basura por defecto"
metadata:
  node_type: memory
  type: feedback
  originSessionId: 68d77ea5-2362-4d69-921f-8a8be899b0d4
---

Al analizar `comments` en fix_metadata/fix_comments.py (`analyze_comment`), además de los issues ya cubiertos (vacío/corto/largo/repetido/basura), hay que revisar si el comment trae secciones tipo "About the Author", "Praise", "Reviews", "Excerpt" (biografía del autor, elogios/reseñas de prensa, extracto del libro) pegadas a la sinopsis.

**Why:** Yolanda ha visto comments HTML que incluyen estas secciones además de la sinopsis real; eso alarga el texto y podría dispararse como ISSUE_LONG o similar, pero no es basura — es contenido legítimo que simplemente no es "solo sinopsis". El HTML en sí (tags, estructura) NO debe tratarse como señal de basura por defecto.

**How to apply:** cuando se retome el desarrollo de fix_comments.py: (1) no asumir que un comment con mucho marcado HTML o muy largo es basura solo por eso — distinguir "sinopsis + material adicional legítimo" de basura real; (2) considerar detectar/etiquetar estas secciones (About the Author, Praise, Reviews, Excerpt) como su propio caso, en vez de solo penalizar por longitud. Ver [[fix-metadata-consolidation-plan]].

Actualización 2026-07-12: añadida red de tests para fix_comments.py (tests/test_fix_metadata.py) — 22 tests nuevos (strip_html/normalize_text, analyze_comment por cada issue: vacío/corto/largo/repetido/basura-frase/basura-sitio/basura-url/basura-mojibake, duplicate_fingerprint), 133 tests totales en verde. Escritos por bash heredoc + verificación de bytes nulos (0) y compilación, no con Edit/Write (carpeta en OneDrive). Sigue pendiente: (2) _JUNK_PHRASES/_SITE_MARKS solo cubren español, no basura en inglés.

Actualización 2026-07-12 (2): implementada la detección de secciones extra. Nueva función `detect_extra_sections(text)` en fix_comments.py: busca líneas-cabecera cortas (≤60 chars) tipo "About the Author", "Praise for...", "Editorial Reviews", "Excerpt" (las etiquetas de bloque HTML ya se convierten en saltos de línea vía strip_html, así que una cabecera envuelta en `<b>`/`<h*>` queda en su propia línea). `analyze_comment` mide corto/largo SOLO sobre el texto anterior a la primera cabecera (la sinopsis real), no sobre el texto completo — así un apéndice largo de reseñas ya no dispara "largo" falso, y una sinopsis real muy corta con biografía larga pegada SÍ se marca "corto" correctamente (antes se libraba). Si la cabecera aparece en los primeros 20 caracteres (sin sinopsis previa real) se usa el texto completo como fallback.

CORRECCIÓN 2026-07-12 (importante, releer si se vuelve a tocar este módulo): mi primera implementación creó un código de issue separado `ISSUE_EXTRA`/`material_extra` tratando las secciones extra como contenido legítimo (ni basura ni nada). Yolanda corrigió: **las secciones extra SÍ son basura** (`ISSUE_JUNK`/`basura`) — no son sinopsis, son relleno. Lo que NO es basura por defecto es el marcado HTML en sí (negrita, párrafos, listas, etc.) — nunca se debe marcar basura solo por tener HTML. Se eliminó `ISSUE_EXTRA` por completo; `detect_extra_sections` ahora solo sirve para (a) recortar el texto a medir en corto/largo y (b) añadir `ISSUE_JUNK` cuando aparece alguna sección. `code_order` en action.py volvió a 5 códigos: vacio, corto, largo, repetido, basura (sin material_extra). 144 tests totales en verde (incluye test explícito de que HTML "normal" sin estas secciones NO se marca basura). FixMetadata.zip reconstruido (python zipfile, mismo listado de ficheros, sin __pycache__/.build) y verificado ÍNTEGRO con verificar_plugin.py.

DECISIÓN 2026-07-12: se ELIMINÓ la detección de comentarios "duplicado" (sinopsis compartida entre libros) de la acción "Check comments" en action.py — Yolanda: tener libros repetidos en la biblioteca es normal, no debe marcarse como problema. Se quitó la Fase de fingerprinting cross-book y `ISSUE_DUPLICATE` de `code_order`/mensajes/tooltip; la función pura `duplicate_fingerprint` sigue en fix_comments.py (con sus tests) por si se reutiliza para otra cosa, pero ya no se llama desde action.py. Los códigos de issue activos ahora: vacio, corto, largo, repetido, basura, material_extra.
