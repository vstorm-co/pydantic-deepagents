---
name: data-formats
description: "Working with diverse data formats: binary, text, structured, and custom"
tags: [data, parsing, formats, benchmark]
version: "1.0.0"
---

# Data Formats

How to work with diverse and unknown data formats.

## Format Detection

Always inspect before parsing:

```bash
file <filename>                    # MIME type detection
xxd <filename> | head -5           # hex dump (first bytes)
head -3 <filename>                 # text preview
python3 -c "
with open('<filename>', 'rb') as f:
    h = f.read(16)
    print(h, h.hex())
"
```

## Common Formats

### Binary
- **Magic bytes**: Most binary formats start with a signature (ELF: `\x7fELF`, PNG: `\x89PNG`)
- **Endianness**: Check if little-endian or big-endian (`struct.unpack('<I', ...)` vs `'>I'`)
- **Alignment**: Fields are often aligned to 4 or 8 bytes
- **Offsets**: Binary headers often contain offsets to other sections

### Structured text
- **CSV/TSV**: Check delimiter (comma, tab, pipe), quoting, header row
- **JSON**: `python3 -c "import json; json.load(open('f'))"`
- **YAML**: Check indentation, anchors/aliases
- **TOML**: `python3 -c "import tomllib; ..."`
- **XML**: Check encoding declaration, namespaces

### Checkpoints / Model files
- **PyTorch**: `.pt`, `.pth` → `torch.load(f, map_location='cpu')`
- **TensorFlow**: `.ckpt` → index + data files, use `tf.train.load_checkpoint()`
- **NumPy**: `.npy`, `.npz` → `numpy.load()`
- **HuggingFace**: `config.json` + `model.safetensors`
- **ONNX**: `onnx.load()`

### Database files
- **SQLite**: `file` says "SQLite 3.x database" → `sqlite3 <file> ".tables"`
- **WAL files**: SQLite write-ahead log — recover with `sqlite3` PRAGMA
- **CSV dumps**: Often need schema inference

## Parsing Strategies

### Unknown binary format
1. Hex dump first 256 bytes: `xxd file | head -16`
2. Look for magic bytes, version numbers, string tables
3. Check file size — does it suggest a pattern? (e.g., N * record_size)
4. Look for documentation of the format online
5. Write a minimal parser, test on known values

### Large structured files
1. Never load entirely — sample first: `head`, `tail`, `shuf -n 10`
2. Check consistency: are all lines the same format?
3. Count fields: `head -1 file | awk -F',' '{print NF}'`
4. Watch for: mixed types, missing values, encoding issues

### Multi-file datasets
1. List all files and sizes
2. Look for manifest/index files (often JSON or CSV)
3. Check naming patterns — timestamps, sequence numbers, shards
4. Process one file first, then generalize

## Common Pitfalls

- Assuming UTF-8 when the file is Latin-1 or binary
- Assuming CSV when it's TSV (or vice versa)
- Ignoring the header row
- Not handling quoted fields with embedded delimiters
- Reading binary files as text (corrupts data)
- Endianness mismatch (x86 is little-endian, network byte order is big-endian)
