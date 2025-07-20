# Railway FastAPI Deployment Template

This template shows exactly what you need to deploy any FastAPI service on Railway, based on the FastAPI-HUB deployment.

## Required Files

### 1. `main.py`
```python
from fastapi import FastAPI
import os
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(title="Your Service Name", description="Service description")

@app.get("/")
async def root():
    return {
        "status": "running",
        "service": os.getenv("RAILWAY_SERVICE_NAME", "unknown"),
        "message": "Hello from Railway!"
    }

@app.get("/health")
async def health():
    return {"status": "healthy"}

# Add your endpoints here
@app.post("/your-endpoint")
async def your_endpoint(data: dict):
    try:
        # Your logic here
        return {"result": "success", "data": data}
    except Exception as e:
        logger.error(f"Error in endpoint: {e}")
        return {"error": str(e)}, 500

@app.on_event("startup")
async def startup_event():
    logger.info(f"Service '{os.getenv('RAILWAY_SERVICE_NAME', 'unknown')}' starting up...")
    # Add any startup logic here

if __name__ == "__main__":
    # This runs locally for testing - Railway uses railway.json instead
    import uvicorn
    uvicorn.run(app, host="::", port=int(os.getenv("PORT", 8000)))
```

### 2. `requirements.txt`
```txt
fastapi==0.100.0
hypercorn==0.14.4
# Add your dependencies here
# httpx==0.24.1  # for HTTP requests
# pydantic==2.0.0  # for data models
```

### 3. `railway.json`
```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": {
    "builder": "NIXPACKS"
  },
  "deploy": {
    "startCommand": "hypercorn main:app --bind \"[::]:$PORT\""
  }
}
```

### 4. `.gitignore` (optional but recommended)
```
__pycache__/
*.py[cod]
*$py.class
.env
.venv/
venv/
*.egg-info/
.pytest_cache/
```

## Railway Environment Variables

Railway automatically provides:
- `PORT` - Port your service should bind to
- `RAILWAY_SERVICE_NAME` - Your service name
- `RAILWAY_SERVICE_ID` - Unique service identifier
- `RAILWAY_ENVIRONMENT_NAME` - Environment name (production, staging, etc.)
- `RAILWAY_PROJECT_ID` - Project identifier

Add custom variables in Railway dashboard under Variables tab.

## Deployment Steps

1. **Create Railway project:**
   ```bash
   railway login
   railway init
   ```

2. **Add these files to your repository**

3. **Deploy:**
   ```bash
   railway up
   ```

4. **Set up custom domain (optional):**
   - Go to Railway dashboard
   - Select your service
   - Add custom domain in Settings tab

## Internal Service Communication

If your service needs to call other Railway services:

```python
import httpx

async def call_other_service():
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://other-service.railway.internal:8000/endpoint",
            json={"data": "value"}
        )
        return response.json()
```

## FastAPI-HUB Integration (optional)

To register with FastAPI-HUB:

```python
import httpx
import asyncio

async def register_with_hub():
    try:
        response = await httpx.AsyncClient().post(
            "http://fastapi-556cf929.railway.internal/register",
            json={
                "name": "your-service-name",
                "internal_url": f"http://{os.getenv('RAILWAY_SERVICE_NAME')}.railway.internal:8000",
                "endpoints": [
                    {
                        "path": "/your-endpoint",
                        "description": "What your endpoint does",
                        "input_schema": {
                            "param1": "string",
                            "param2": "integer"
                        }
                    }
                ]
            }
        )
        if response.status_code == 200:
            logger.info("Successfully registered with FastAPI-HUB")
        else:
            logger.warning(f"Hub registration failed: {response.status_code}")
    except Exception as e:
        logger.warning(f"Could not register with hub: {e}")

@app.on_event("startup")
async def startup_event():
    logger.info("Service starting up...")
    # Register with hub after a brief delay
    asyncio.create_task(asyncio.sleep(2))
    asyncio.create_task(register_with_hub())
```

## Common Patterns

### Error Handling
```python
from fastapi import HTTPException

@app.post("/endpoint")
async def endpoint(data: dict):
    try:
        # Your logic
        return {"result": data}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
```

### Logging
```python
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.post("/endpoint")
async def endpoint(data: dict):
    logger.info(f"Processing request: {data}")
    # Your logic
    logger.info("Request completed successfully")
```

### Environment Configuration
```python
import os

# Configuration from environment variables
class Config:
    SERVICE_NAME = os.getenv("RAILWAY_SERVICE_NAME", "unknown")
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    API_KEY = os.getenv("API_KEY")  # Set in Railway dashboard
    
    @property
    def internal_url(self):
        return f"http://{self.SERVICE_NAME}.railway.internal:8000"

config = Config()
```

## Testing Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export PORT=8000
export RAILWAY_SERVICE_NAME=your-service

# Run locally
python main.py
```

## Troubleshooting

**Service not accessible:**
- Ensure using IPv6 binding: `--bind "[::]:$PORT"`
- Check PORT environment variable is being used
- Verify service name matches Railway dashboard

**Internal communication fails:**
- Use `service-name.railway.internal` format
- Ensure target service is deployed and running
- Check service names in Railway dashboard

**Deployment fails:**
- Verify `requirements.txt` has all dependencies
- Check `railway.json` syntax
- Review build logs in Railway dashboard

This template gives you everything needed to deploy FastAPI services on Railway successfully.