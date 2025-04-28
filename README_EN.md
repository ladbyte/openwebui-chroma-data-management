# Chroma Demo Project
## Project Background

This project is a tool specifically designed for viewing data in OpenWebUI's vector database. It allows users to easily connect and browse Chroma vector databases used by OpenWebUI, view Collections information, retrieve vector data content, and reconstruct original file contents.

## Features

- **Initialize Chroma Client**: Quickly connect to local or remote Chroma databases
- **Manage Collections**: Create, delete, and query Collections
- **Batch Process Collections**: Efficiently handle large numbers of Collections with multi-threading support
- **Filename-Collection Mapping**: Automatically establish mapping between filenames and Collections
- **File Content Reconstruction**: Extract and reconstruct original file contents from Collections

## Configuration

1. **Install Dependencies**:
```bash
pip install -r requirements.txt
```

2. **Configure Database Path**:
When initializing `ChromaClient`, directly pass the database path parameter. For example:
```python
# Specify database path when initializing client
client = ChromaClient(path="./chroma_db")
```

Or configure through environment variables:
```python
import os
# Read database path from environment variable
db_path = os.getenv("CHROMA_DB_PATH", "./chroma_db")
client = ChromaClient(path=db_path)
```

3. **Log Configuration**:
Log files are stored by default in the `logs` directory with timestamp naming. The log level is DEBUG, with output to both console and log files.