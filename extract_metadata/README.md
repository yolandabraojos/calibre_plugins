# Extract Metadata Plugin

A Calibre plugin that automatically extracts metadata from EPUB and AZW3 files, including generator information and book producer details.

## Features

- **Generator & Producer Extraction**: Extracts generator and book producer metadata
- **Multiple Format Support**: Works with EPUB and AZW3 files
- **Custom Field Storage**: Stores data in `#generator` and `#book_producer` fields
- **Batch Processing**: Process multiple books at once
- **Robust Parsing**: Multiple fallback methods for XML parsing
- **Flexible**: Handles various attribute orderings and formats

## Installation

1. Download the plugin ZIP file
2. In Calibre, go to `Preferences` → `Plugins` → `Load plugin from file`
3. Select the plugin ZIP file
4. Restart Calibre

## Required Custom Fields

Before using the plugin, create these custom fields in Calibre:

| Field | Lookup Name | Type | Purpose |
|-------|-------------|------|---------|
| Generator | `generator` | Text | Software/tool that generated the e-book |
| Book Producer | `book_producer` | Text | Book producer/contributor information |
| Title OPF | `title_opf` | Text | Title extracted from OPF metadata |
| Subjects | `subjects` | Text | Subject tags/keywords extracted from metadata |

### Creating Custom Fields

1. Go to `Preferences` → `Add your own columns`
2. Click `Add custom column` button
3. For each field above, fill in:
   - **Lookup name**: Use the value from the "Lookup Name" column above
   - **Column heading**: Use the value from the "Field" column above (or your preferred display name)
   - **Column type**: `Text`
4. Click `OK` for each field
5. Restart Calibre

**Important**: All four fields are required. The plugin will display an error if any are missing.

## Usage

1. Select one or more books in your library
2. Click the **Extract Metadata** button in the toolbar
3. The plugin extracts and stores metadata in the custom fields
4. A summary dialog shows results

## Supported Formats

- **EPUB**: Standard e-book format
- **AZW3**: Amazon's e-book format

## Building the Plugin

### Prerequisites

- Windows with PowerShell or Command Prompt
- Python (optional, for testing)

### Build Steps

**Option 1: From PowerShell (Recommended)**

From the project root directory:
```powershell
cmd.exe /c ".build\build.cmd"
```

Or navigate to `.build` first:
```powershell
cd .build
cmd.exe /c build.cmd
cd ..
```

**Option 2: From Command Prompt**

From the project root directory:
```cmd
.build\build.cmd
```

### Output

The build script will create a ZIP file in the parent `build` directory:
```
../../build/extract_metadata-v1.3.1.zip
```

### What Gets Packaged

The build script creates a ZIP file containing:
- `__init__.py` - Plugin wrapper
- `action.py` - Main plugin logic
- `extractor.py` - Metadata extraction functions
- `jobs.py` - Background job handling
- `plugin-import-name-extract_metadata.txt` - Plugin identifier
- `README.md` - Documentation
- `CHANGELOG.md` - Change history
- `images/` - Plugin icons

### Installation

1. Copy the generated ZIP file to your Calibre plugins directory or use Calibre's plugin loader
2. In Calibre: `Preferences` → `Plugins` → `Load plugin from file`
3. Select the ZIP file and restart Calibre

## Debugging

### Running Calibre in Debug Mode

To test and debug the plugin with detailed logging output:

**From PowerShell (Recommended)**

From the project root directory:
```powershell
cmd.exe /c ".build\debug.cmd"
```

Or using calibre-debug directly:
```powershell
calibre-debug -e __init__.py
```

**From Command Prompt**

From the project root directory:
```cmd
.build\debug.cmd
```

Or:
```cmd
calibre-debug -e __init__.py
```

### Enabling DEBUG Logging

By default, the plugin logs at `INFO` level. To see detailed DEBUG logs, modify the logging level in [extractor.py](extractor.py#L23):

1. Open `extractor.py`
2. Find line 23 and 27 (the logger configuration):
   ```python
   ch.setLevel(logging.INFO)     # Line 23
   ...
   logger.setLevel(logging.INFO)  # Line 27
   ```

3. Change both `logging.INFO` to `logging.DEBUG`:
   ```python
   ch.setLevel(logging.DEBUG)     # Change INFO to DEBUG
   ...
   logger.setLevel(logging.DEBUG)  # Change INFO to DEBUG
   ```

4. Save the file
5. Run Calibre in debug mode again:
   ```powershell
   calibre-debug -e __init__.py
   ```

### Log Levels

The plugin supports the following log levels (from least to most verbose):

- **ERROR**: Only shows errors and critical issues
- **WARNING**: Shows warnings and errors
- **INFO** (default): Shows general information, warnings, and errors
- **DEBUG**: Shows detailed debugging information including file operations and XML parsing

### What Happens in Debug Mode

When running in debug mode:
- Calibre GUI launches with the plugin loaded in the current directory
- All logging output is displayed in the console at the configured level
- You can see in real-time what the plugin is doing
- Python exceptions and tracebacks are printed to the console
- With DEBUG enabled, you'll see detailed information about:
  - File opening and processing
  - XML parsing steps
  - Metadata extraction results
  - Container.xml reading
  - OPF file location

### Viewing Logs

The plugin logs to the console with the format:
```
YYYY-MM-DD HH:MM:SS - LEVEL - message
```

Example DEBUG output:
```
2026-02-28 10:30:45,123 - DEBUG - Abriendo archivo EPUB: mybook.epub
2026-02-28 10:30:45,234 - DEBUG - OPF localizado vía container.xml: OEBPS/content.opf
2026-02-28 10:30:45,345 - INFO - Extracción finalizada. Resultado: Gen='calibre', Prod='calibre', Título='My Book'
```

### Common Debug Scenarios

**Testing metadata extraction:**
1. Enable DEBUG logging in extractor.py
2. Run Calibre in debug mode
3. Select one or more books
4. Click "Extract Metadata"
5. Check the console output for extraction details

**Checking custom field creation:**
1. Run in debug mode
2. The plugin will log validation results for custom fields
3. If fields are missing, an error message will be displayed

**Debugging XML parsing:**
1. Enable DEBUG logging
2. Run debug mode and process a book
3. Look for messages about OPF file location and XML parsing steps

## Technical Details

The plugin uses multiple methods to ensure robust extraction:

1. **ElementTree with Namespaces**: Standard XML parsing
2. **Regex Pattern Matching**: Flexible pattern matching for various formats
3. **EXTH Fallback**: Extracts metadata from MOBI EXTH records (AZW3)

The book producer detection searches for `<dc:contributor>` elements with `opf:role="bkp"`, supporting various attribute orderings.

## License

GPL v3
