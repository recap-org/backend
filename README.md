# Recap Template Backend

A Python FastAPI backend for dynamically generating and serving cookiecutter templates. This backend replaces the pre-compilation approach with on-demand template generation.

## Features

- **Dynamic Template Generation**: Generate cookiecutter templates on-the-fly based on user parameters
- **RESTful API**: Clean API endpoints for listing templates and generating downloads
- **CORS Support**: Ready for integration with the Jekyll static frontend
- **Multiple Templates**: Supports data, article, presentation, and devcontainer templates
- **Flexible Parameters**: Customize R version, LaTeX packages, author information, and more

## API Endpoints

### 1. Root Endpoint
```
GET /
```
Returns API information and available endpoints.

### 2. List Templates
```
GET /templates
```
Returns all available cookiecutter templates with their metadata.

**Response:**
```json
{
  "templates": {
    "data": {
      "path": "./data",
      "title": "project - Data",
      "description": "A data science project structure"
    },
    "article": {
      "path": "./article",
      "title": "tex - Article",
      "description": "A template for a research article"
    }
  }
}
```

### 3. Get Template Configuration
```
GET /templates/{template_name}/config
```
Returns the configuration options available for a specific template.

**Example:**
```
GET /templates/data/config
```

### 4. Generate Template (GET)
```
GET /generate?template_name=data&project_name=My%20Project&latex=auto&...
```

**Parameters:**
- `template_name` (required): Template to generate (data, article, presentation, devcontainer)
- `project_name` (optional): Name of the project (default: "My Project")
- `r` (optional): Use R? (default: true)
- `r_version` (optional): R version (default: "4.5.1")
- `latex` (optional): LaTeX package list - auto/full/curated (default: "auto")
- `first_name` (optional): Author's first name (default: "Morgan")
- `last_name` (optional): Author's last name (default: "Doe")
- `email` (optional): Author's email (default: "morgan.doe@example.com")
- `institution` (optional): Author's institution (default: "Your Institution")

**Response:** ZIP file download

**Example:**
```
GET /generate?template_name=data&project_name=My%20Research&latex=full&first_name=Jane&last_name=Smith
```

### 5. Generate Template (POST)
```
POST /generate
Content-Type: application/json
```

**Request Body:**
```json
{
  "template_name": "data",
  "project_name": "My Research Project",
  "r": true,
  "r_version": "4.5.1",
  "latex": "auto",
  "first_name": "Jane",
  "last_name": "Smith",
  "email": "jane.smith@university.edu",
  "institution": "University of Example"
}
```

**Response:** ZIP file download

## Setup and Installation

### Option 1: Local Development

1. **Install Python 3.11+**

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the server:**
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

4. **Access the API:**
   - API: http://localhost:8000
   - Interactive docs: http://localhost:8000/docs
   - Alternative docs: http://localhost:8000/redoc

### Option 2: In an existing container/devcontainer

If you're already inside a container or VS Code Dev Container, just run:

```bash
./start.sh
```

This uses the repo's virtual environment and launches Uvicorn.

## Frontend Integration

Update your Jekyll site's JavaScript to call the backend API instead of using pre-compiled zips.

### Example: Update `template-form.js`

Replace the hardcoded download URLs with API calls:

```javascript
// Old approach (hardcoded zip files)
var href = baseUrl + '/downloads/' + zipName;

// New approach (dynamic API generation)
var apiUrl = 'http://localhost:8000/generate';
var params = new URLSearchParams({
    template_name: 'data',
    project_name: 'My Project',
    latex: latex,
    r: true,
    r_version: '4.5.1',
    first_name: firstName,
    last_name: lastName,
    email: email,
    institution: institution
});
var href = apiUrl + '?' + params.toString();
```

### CORS Configuration

For production, update the CORS settings in `app/main.py`:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://yourdomain.github.io"],  # Your Jekyll site
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

## Development

### Project Structure

```
backend/
├── app/
│   ├── __init__.py
│   └── main.py          # Main FastAPI application
├── cookiecutter/        # Cookiecutter templates (moved to repo root)
├── requirements.txt     # Python dependencies
├── .gitignore
├── start.sh             # Quick start in container/devcontainer
└── README.md
```

### Running Tests

The API includes interactive documentation at `/docs` where you can test all endpoints.

### Adding New Templates

1. Add the template to `cookiecutter/`
2. Update `cookiecutter/cookiecutter.json`
3. The API will automatically detect and serve the new template

## Environment Variables

For production deployments, consider adding:
- `ALLOWED_ORIGINS`: Comma-separated list of allowed CORS origins
- `PORT`: Server port (default: 8000)

## API Documentation

Once running, visit:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## License

See LICENSE file for details.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request