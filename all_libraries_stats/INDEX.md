# Documentación - All Libraries Stats Plugin v1.2.2

## 🗂️ Índice de Documentos

Una guía completa para encontrar lo que necesitas en la documentación del plugin.

---

## 📍 Empezar Aquí

### Para Nuevos Usuarios

**¿Primera vez?** → Lee en este orden:

1. **[START_HERE.md](START_HERE.md)** (5 min)
   - Qué hace el plugin
   - Resumen de v1.2.2
   - Qué documento leer según tu necesidad
   
2. **[QUICK_START.md](QUICK_START.md)** (5 min)
   - Instalación rápida paso-a-paso
   - Verificación de funcionalidad
   - Troubleshooting rápido

3. **[DUPLICATES_GUIDE.md](DUPLICATES_GUIDE.md)** (10 min, si tienes duplicados)
   - Cómo funciona la detección nuevo título+autor
   - Ejemplos con coautores
   - Cómo consolidar duplicados

### Para Casos Específicos

| Necesidad | Documento | Tiempo |
|-----------|-----------|--------|
| **Instalar en Calibre** | [QUICK_START.md](QUICK_START.md) | 5 min |
| **Guía paso-a-paso detallada** | [INSTALLATION.md](INSTALLATION.md) | 15 min |
| **Entender la lógica de duplicados** | [DUPLICATES_GUIDE.md](DUPLICATES_GUIDE.md) | 10 min |
| **Detalles técnicos/código** | [TECHNICAL_DOCS.md](TECHNICAL_DOCS.md) | 20 min |
| **Batching y rendimiento** | [BATCH_PROCESSING.md](BATCH_PROCESSING.md) | 10 min |
| **Arquitectura (v1.2.2)** | [ARCHITECTURE_REFACTORING.md](ARCHITECTURE_REFACTORING.md) | 15 min |
| **Debugging y modo depuración** | [DEBUGGING_GUIDE.md](DEBUGGING_GUIDE.md) | 15 min |
| **Error #language_code** | [ERROR_LANGUAGE_CODE_INVESTIGATION.md](ERROR_LANGUAGE_CODE_INVESTIGATION.md) | 10 min |
| **Ver cambios recientes** | [CHANGELOG.md](CHANGELOG.md) | 5 min |

---

## 📖 Documentos Principales

### 1. START_HERE.md
**Punto de entrada al plugin**

✓ Qué necesitas saber  
✓ Por dónde empezar (según tu tiempo)  
✓ Cambios en v1.2.2  
✓ Preguntas frecuentes  

**Para**: Todos los usuarios  
**Tiempo**: 5 minutos

---

### 2. QUICK_START.md
**Instalación y configuración rápida**

✓ Crear 3 campos en Calibre (paso-a-paso)  
✓ Instalar plugin  
✓ Configurar rutas  
✓ Ejecutar análisis  
✓ Verificar que funciona  
✓ Ejemplo real con datos  
✓ Troubleshooting rápido  

**Para**: Usuarios que quieren empezar YA  
**Tiempo**: 5-10 minutos  
**Requisito previo**: Calibre instalado

---

### 3. INSTALLATION.md
**Guía completa paso-a-paso**

✓ Requisitos del sistema  
✓ Creación detallada de campos  
✓ Instalación del plugin  
✓ Configuración con pantallas  
✓ Ejecución y análisis  
✓ Verificación exhaustiva  
✓ Troubleshooting avanzado  

**Para**: Usuarios que prefieren guías detalladas  
**Tiempo**: 15-30 minutos  
**Requisito previo**: Acceso a Calibre Preferences

---

### 4. DUPLICATES_GUIDE.md
**Guía completa de duplicados (v1.2.0+)**

✓ Qué significa búsqueda título+autor  
✓ 8+ ejemplos detallados con datos reales  
✓ Tabla de escenarios (SÍ/NO)  
✓ Ventajas vs búsqueda por título solo  
✓ Cómo consolidar duplicados  
✓ Casos especiales (Unknown, tildes, etc.)  
✓ Integración de los 3 campos  
✓ Flujo de consolidación  

**Para**: Usuarios con duplicados, casos complejos  
**Tiempo**: 10-15 minutos  
**Requisito previo**: Plugin instalado

---

### 5. README.md
**Descripción general del plugin**

✓ Overview del plugin  
✓ Características principales  
✓ Tabla de campos  
✓ Ejemplo de salida  
✓ Instalación (resumen)  
✓ Requisitos y compatibilidad  

**Para**: Vista general rápida  
**Tiempo**: 5 minutos

---

### 6. TECHNICAL_DOCS.md
**Documentación técnica interna**

✓ Arquitectura del plugin  
✓ Flujo de ejecución (diagrama)  
✓ Estructura de datos  
✓ Base de datos (SQLite)  
✓ Queries SQL utilizadas  
✓ Campos personalizados  
✓ Configuración almacenada  
✓ Métodos principales  
✓ Cambios en v1.2.0 (detalle técnico)  
✓ Casos de uso técnicos  
✓ Testing recomendado  
✓ Notas de implementación  

**Para**: Desarrolladores, gente técnica  
**Tiempo**: 20-30 minutos  
**Requisito previo**: Conocimiento de Python/Calibre

---

### 7. CHANGELOG.md
**Historial de versiones**

✓ v1.2.0: Cambios principales  
✓ v1.1.0: Soporte múltiples rutas  
✓ v1.0.0: Release inicial  
✓ Comparación entre versiones  
✓ Planificación de futuras versiones  
✓ Dependencias y compatibilidad  
✓ Notas de desarrollo  

**Para**: Ver qué cambió, actualizar  
**Tiempo**: 5-10 minutos

---

## 🎯 Problemas y Soluciones

### "No aparecen datos"
1. Lee: [QUICK_START.md - Troubleshooting](QUICK_START.md#troubleshooting-r%C3%A1pido)
2. O: [INSTALLATION.md - Verificar instalación](INSTALLATION.md)

### "¿Qué son los duplicados?"
1. Lee: [DUPLICATES_GUIDE.md](DUPLICATES_GUIDE.md)
2. O: [START_HERE.md - Ejemplo Real](START_HERE.md#ejemplo)

### "¿Cómo configuro el plugin?"
1. Lee: [QUICK_START.md - paso 2](QUICK_START.md#paso-2-configuración-rápida-2-minutos)
2. O: [INSTALLATION.md - paso 4](INSTALLATION.md#paso-4-configurar-el-plugin)

### "Quiero entender la técnica"
1. Lee: [TECHNICAL_DOCS.md](TECHNICAL_DOCS.md)
2. O: [TECHNICAL_DOCS.md - Cambios en v1.2.0](TECHNICAL_DOCS.md#cambios-clave-en-v120)

### "¿Qué cambió en v1.2.0?"
1. Lee: [START_HERE.md - Cambios](START_HERE.md#principales-cambios-en-v120)
2. O: [CHANGELOG.md - v1.2.0](CHANGELOG.md#120---marzo-2024)

---

## 🗺️ Mapa de Documentos

```
ALL LIBRARIES STATS PLUGIN
│
├─ ÍNDICE (este archivo)
│  └─ Te ayuda a navegar toda la documentación
│
├─ START_HERE.md
│  ├─ ¿Qué hace el plugin?
│  ├─ Flujo de instalación
│  ├─ Cambios v1.2.0
│  ├─ Preguntas comunes
│  └─ Referencias cruzadas
│
├─ QUICK_START.md (RECOMENDADO PARA EMPEZAR)
│  ├─ 1. Crear campos (Paso rápido)
│  ├─ 2. Configurar
│  ├─ 3. Ejecutar
│  ├─ 4. Verificar
│  ├─ Ejemplo real
│  └─ Troubleshooting
│
├─ INSTALLATION.md (Guía detallada)
│  ├─ Requisitos
│  ├─ Crear campos (paso-a-paso con pantallas)
│  ├─ Instalar plugin
│  ├─ Configurar (detallado)
│  ├─ Ejecutar (con explicaciones)
│  ├─ Verificar
│  └─ Troubleshooting avanzado
│
├─ DUPLICATES_GUIDE.md (Guía de duplicados)
│  ├─ Qué significa título+autor
│  ├─ 8+ ejemplos
│  ├─ Tabla de escenarios
│  ├─ Cómo consolidar
│  ├─ Casos especiales
│  └─ Flujo recomendado
│
├─ README.md (Overview)
│  ├─ Descripción
│  ├─ Características
│  ├─ Tabla de campos
│  └─ Requisitos
│
├─ TECHNICAL_DOCS.md (Técnico)
│  ├─ Arquitectura
│  ├─ Flujo de ejecución
│  ├─ Métodos principales
│  ├─ Queries SQL
│  ├─ Cambios v1.2.0
│  ├─ BATCH PROCESSING v1.2.1 (NEW)
│  └─ Testing
│
├─ BATCH_PROCESSING.md (Rendimiento v1.2.1)
│  ├─ Qué es batch processing
│  ├─ Cómo funciona en el plugin
│  ├─ Tamaños de batch
│  ├─ Implementación técnica
│  ├─ Análisis de rendimiento
│  ├─ Casos de uso
│  └─ FAQ
└─ CHANGELOG.md (Historial)
   ├─ v1.2.0: Nuevas características
   ├─ v1.1.0: Soporte múltiples rutas
   ├─ v1.0.0: Release inicial
   └─ Comparación de versiones
```

---

## 📚 Guías por Módulo

### Instalación
1. [QUICK_START.md](QUICK_START.md) - 5 minutos
2. [INSTALLATION.md](INSTALLATION.md) - 15 minutos (detallado)
3. [TECHNICAL_DOCS.md - Base de Datos](TECHNICAL_DOCS.md#base-de-datos) - si hay errores

### Uso
1. [README.md](README.md) - Overview
2. [QUICK_START.md - Ejemplo Real](QUICK_START.md#ejemplo-real) - ver datos
3. [DUPLICATES_GUIDE.md](DUPLICATES_GUIDE.md) - si tienes duplicados

### Configuración
1. [QUICK_START.md - Paso 2](QUICK_START.md#paso-2-configuración-rápida-2-minutos) - rápido
2. [INSTALLATION.md - Paso 4](INSTALLATION.md#paso-4-configurar-el-plugin) - detallado

### Campos Personalizados
1. [QUICK_START.md - Paso 1](QUICK_START.md#paso-1-instalación-rápida-2-minutos) - crear campos
2. [INSTALLATION.md - Paso 2](INSTALLATION.md#paso-2-crear-campos-personalizados) - crear detallado
3. [TECHNICAL_DOCS.md - Campos](TECHNICAL_DOCS.md#campos-personalizados) - especificaciones

### Detección de Duplicados
1. [DUPLICATES_GUIDE.md](DUPLICATES_GUIDE.md) - casos completos
2. [TECHNICAL_DOCS.md - v1.2.0](TECHNICAL_DOCS.md#cambios-clave-en-v120) - técnica
3. [CHANGELOG.md - v1.2.0](CHANGELOG.md#120---marzo-2024) - qué cambió

### Troubleshooting
1. [QUICK_START.md - Troubleshooting](QUICK_START.md#troubleshooting-rápido) - problemas comunes
2. [INSTALLATION.md - Troubleshooting](INSTALLATION.md#troubleshooting-avanzado) - problemas avanzados
3. [TECHNICAL_DOCS.md - Errores](TECHNICAL_DOCS.md#manejo-de-errores) - errores técnicos
### Rendimiento y Batching (v1.2.1)
1. [BATCH_PROCESSING.md](BATCH_PROCESSING.md) - Guía completa
2. [TECHNICAL_DOCS.md - Batch Processing](TECHNICAL_DOCS.md#implementación-de-batch-processing-en-detalle) - detalles técnicos
3. [CHANGELOG.md - v1.2.1](CHANGELOG.md#121---marzo-2024-procesamiento-en-batches) - novedades
### Desarrollo Técnico
1. [TECHNICAL_DOCS.md](TECHNICAL_DOCS.md) - arquitectura completa
2. [CHANGELOG.md - v1.2.0 Técnico](CHANGELOG.md#-cambios-técnicos) - cambios de código

---

## 🔍 Búsqueda Rápida

### Términos Clave

| **Términos Clave** | **Documentos** |
|---|---|
| **Instalación** | QUICK_START.md, INSTALLATION.md |
| **Campos personalizados** | QUICK_START.md, INSTALLATION.md, TECHNICAL_DOCS.md |
| **Duplicados** | DUPLICATES_GUIDE.md, START_HERE.md |
| **Título + autor** | DUPLICATES_GUIDE.md, TECHNICAL_DOCS.md |
| **Coautores** | DUPLICATES_GUIDE.md, TECHNICAL_DOCS.md |
| **SQLite** | TECHNICAL_DOCS.md |
| **v1.2.0** | CHANGELOG.md, START_HERE.md, TECHNICAL_DOCS.md |
| **v1.2.1: Batching** | CHANGELOG.md, BATCH_PROCESSING.md, TECHNICAL_DOCS.md |
| **Rendimiento** | BATCH_PROCESSING.md, QUICK_START.md, README.md |
| **Troubleshooting** | QUICK_START.md, INSTALLATION.md, TECHNICAL_DOCS.md |

---

## 📋 Fases de Uso

### Fase 1: Aprender (0-5 min)
→ Lee: [START_HERE.md](START_HERE.md)

### Fase 2: Instalar (5-10 min)
→ Lee: [QUICK_START.md](QUICK_START.md)

### Fase 3: Usar (10-60 min)
→ Lee: [QUICK_START.md - Ejemplo](QUICK_START.md#ejemplo-real) o [INSTALLATION.md](INSTALLATION.md)

### Fase 4: Consolidar Duplicados (60-180 min)
→ Lee: [DUPLICATES_GUIDE.md](DUPLICATES_GUIDE.md)

### Fase 5: Profundizar (opcional)
→ Lee: [TECHNICAL_DOCS.md](TECHNICAL_DOCS.md)

---

## 🎓 Niveles de Complejidad

### Principiante
- [START_HERE.md](START_HERE.md)
- [QUICK_START.md](QUICK_START.md)
- [README.md](README.md)

### Intermedio
- [INSTALLATION.md](INSTALLATION.md)
- [DUPLICATES_GUIDE.md](DUPLICATES_GUIDE.md)

### Avanzado
- [TECHNICAL_DOCS.md](TECHNICAL_DOCS.md)
- [BATCH_PROCESSING.md](BATCH_PROCESSING.md)
- [DEBUGGING_GUIDE.md](DEBUGGING_GUIDE.md)
- [CHANGELOG.md](CHANGELOG.md)

---

## 🐛 Debugging y Errores

### Modo Depuración
Para ejecutar Calibre con logs completos y debug enabled:

```bash
calibre-debug -g
```

Documentación: [DEBUGGING_GUIDE.md](DEBUGGING_GUIDE.md)

### Documentos de Debugging

#### 1. DEBUGGING_GUIDE.md
**Guía completa para debugging del plugin**

✓ Cómo ejecutar en modo depuración (`calibre-debug -g`)  
✓ Interpretación de logs  
✓ Script de test (`test_analyzer.py`)  
✓ Análisis manual de librerías  
✓ Solución de errores comunes  
✓ Recursos útiles  

**Para**: Usuarios con problemas, investigación de bugs  
**Tiempo**: 15-20 minutos  

---

#### 2. ERROR_LANGUAGE_CODE_INVESTIGATION.md
**Investigación del error: "Incorrect number of arguments for function contains"**

✓ Explicación del error  
✓ ¿Es culpa del plugin All Libraries Stats?  
✓ Pasos para investigar  
✓ Soluciones específicas  
✓ Cómo reportar el error  

**Para**: Si recibes este error específico  
**Tiempo**: 10-15 minutos  

---

## Scripts de Debugging

### test_analyzer.py
Script para testing y debugging del plugin sin Calibre.

**Ubicación**: Raíz del plugin

**Uso**:
```bash
python test_analyzer.py "C:\tu\ruta\de\librerías"
```

**Qué hace**:
- Busca librerías en la ruta
- Valida bases de datos
- Cuenta autores y libros
- Genera reporte de estadísticas
- Identifica problemas

**Documentación**: [DEBUGGING_GUIDE.md - Script de Debug](DEBUGGING_GUIDE.md#script-de-debug-test_analyzerpy)

---

## Flujo de Troubleshooting

```
¿Hay error? 
  │
  ├─ ¿Dice "language_code"?
  │  └─ Leer: ERROR_LANGUAGE_CODE_INVESTIGATION.md
  │
  ├─ ¿No aparecen datos?
  │  └─ Leer: QUICK_START.md#troubleshooting
  │
  ├─ ¿Errores al actualizar campos?
  │  └─ Leer: DEBUGGING_GUIDE.md
  │
  └─ ¿Quieres ver logs?
     └─ Ejecutar: calibre-debug -g
        Documentación: DEBUGGING_GUIDE.md
```

---

## 🚀 Ruta Recomendada

```
┌─────────────────────────────────┐
│ 1. START_HERE.md (5 min)        │
│    "¿Qué hace?" + Índice        │
└──────────────┬──────────────────┘
               │
┌──────────────▼──────────────────┐
│ 2. QUICK_START.md (5-10 min)    │
│    Instalar y ejecutar          │
└──────────────┬──────────────────┘
               │
      ┌────────┴────────┐
      │                 │
      │ (Sin problemas) │ (Con problemas)
      │                 │
      ▼                 ▼
┌────────────────│────────────────┐
│3. README.md    │INSTALLATION.md  │
│   (Usar)       │ (Detallado)     │
│                │                 │
│ Si duplicados: │Si duplicados:   │
│ → DUPLICATES_  │ → DUPLICATES_   │
│   GUIDE.md     │   GUIDE.md      │
└────────────────▼────────────────┘
               │
        Opcional:
               │
┌──────────────▼──────────────────┐
│ 4. TECHNICAL_DOCS.md            │
│    (Profundizar en código)      │
└─────────────────────────────────┘
```

---

## 📞 Ayuda Rápida

**¿No encuentras lo que buscas?**

1. Usa Ctrl+F en tu lector de Markdown
2. Busca el término clave en la tabla anterior
3. Lee el documento recomendado
4. Consulta [QUICK_START.md - Troubleshooting](QUICK_START.md#troubleshooting-rápido)

**¿Problema técnico?**
→ Consulta [TECHNICAL_DOCS.md - Manejo de errores](TECHNICAL_DOCS.md#manejo-de-errores)

---

**Última actualización**: Marzo 2024  
**Versión del Plugin**: 1.2.0  
**Documentação Versión**: 1.0
