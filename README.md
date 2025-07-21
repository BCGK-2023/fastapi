# FastAPI-HUB

## What is FastAPI-HUB?

FastAPI-HUB is a dynamic API gateway that automatically routes requests to your microservices. Instead of managing multiple API endpoints, you get a single URL that intelligently forwards requests to the right service.

When microservices register themselves with the hub, it automatically creates public routes for their endpoints. This means you can call `hub.com/example-tool/example-endpoint` and the hub will forward your request to the internal `example-tool` service, handle the response, and send it back to you.

**Key Features:**
- **Single public endpoint** for all your microtools
- **Automatic routing** - services register once, routes appear immediately  
- **Zero configuration** - no manual setup or route definitions
- **Full request logging** - see exactly what's happening
- **Multiple HTTP methods** - supports GET, POST, PUT, DELETE, PATCH
- **Per-endpoint timeouts** - services can specify custom timeout values
- **Heartbeat monitoring** - automatic cleanup of stale services

## Why use it?

**The Problem:**
Without FastAPI-HUB, each microtool needs its own public URL and deployment. If you have 10 tools, you manage 10 different endpoints:
- `image-resizer.myapp.com/resize`
- `text-summarizer.myapp.com/summarize` 
- `pdf-converter.myapp.com/convert`
- ... and 7 more URLs to remember

**The Solution:**
FastAPI-HUB gives you one URL for everything:
- `myapp.com/image-resizer/resize`
- `myapp.com/text-summarizer/summarize`
- `myapp.com/pdf-converter/convert`

**How it works:**
1. **Services register themselves** - Each microtool calls the hub's `/register` endpoint on startup
2. **Routes are created automatically** - Hub creates `POST /tool-name/endpoint` routes instantly
3. **Requests are forwarded** - When users call your public URL, the hub forwards to the internal service
4. **Responses come back** - Hub returns the service's response to the user

**Benefits:**
- **Simpler frontend code** - One base URL for all API calls
- **Easier deployment** - Only the hub needs a public URL
- **Centralized logging** - See all API usage in one place
- **No manual configuration** - Services announce their own capabilities

## Quick Start

Get FastAPI-HUB working in 2 minutes:

### 1. Register a Service
```bash
curl -X POST "your-hub-url.com/register" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "example-tool",
    "internal_url": "http://example-tool.railway.internal:3000",
    "endpoints": [
      {
        "path": "/process",
        "method": "POST",
        "timeout": 30,
        "description": "Process some data",
        "input_schema": {
          "text": "string",
          "number": "integer"
        }
      }
    ]
  }'
```

**Response:**
```json
{
  "status": "success",
  "message": "Service 'example-tool' registered",
  "routes_created": 1
}
```

### 2. Use the New Route
```bash
curl -X POST "your-hub-url.com/example-tool/process" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "hello world",
    "number": 42
  }'
```

### 3. Check the Dashboard
Visit `your-hub-url.com/` to see:
- All registered services
- Available routes  
- Recent request logs

**That's it!** The route `POST /example-tool/process` now exists and forwards requests to your internal service.

## For API Users

### Discover Available Tools
Check the hub dashboard to see all registered services:
```bash
curl "your-hub-url.com/"
```

**Response shows:**
- `services` - All available tools and their endpoints
- `service_count` - Number of registered tools
- `logs` - Recent activity

### Making Requests
All tool endpoints use the same pattern:
```
POST /tool-name/endpoint-name
```

**Request format:**
- Method: `POST`
- Content-Type: `application/json`
- Body: JSON object with the required parameters

**Example:**
```bash
curl -X POST "your-hub-url.com/example-tool/process" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "your input here",
    "number": 123
  }'
```

### Response Handling
- **Success**: Tool's response is returned directly
- **Error**: Hub returns error details:
  ```json
  {
    "error": "Internal service error",
    "details": "Service unavailable"
  }
  ```

### Finding Input Requirements
Each service registration includes `input_schema` showing required parameters:
```json
{
  "text": "string",
  "number": "integer",
  "optional_param": "string"
}
```

## For Service Developers

### Registering Your Service
Call the hub's `/register` endpoint when your service starts up:

```javascript
// Example: Node.js/Bun service registration
await fetch("http://fastapi-hub.railway.internal/register", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    name: "my-awesome-tool",
    internal_url: "http://my-awesome-tool.railway.internal:3000",
    endpoints: [
      {
        path: "/analyze",
        method: "POST",
        timeout: 45,  // Analysis might take longer
        description: "Analyze text data", 
        input_schema: {
          text: "string",
          language: "string",
          detailed: "boolean"
        }
      },
      {
        path: "/summarize",
        method: "POST", 
        timeout: 60,  // Summarization can be slow
        description: "Summarize long text",
        input_schema: {
          text: "string",
          max_length: "integer"
        }
      }
    ]
  })
});
```

### Registration Format
- **name**: Your tool's identifier (used in public URLs)
- **internal_url**: Your service's Railway internal URL
- **endpoints**: Array of endpoints your service provides
  - **path**: Endpoint path (e.g., "/analyze")
  - **method**: HTTP method (GET, POST, PUT, DELETE, PATCH) - defaults to POST
  - **timeout**: Request timeout in seconds - defaults to 30
  - **description**: Human-readable description
  - **input_schema**: Expected JSON parameters and their types

### Best Practices
- **Register on startup**: Call `/register` immediately when your service boots
- **Use descriptive names**: Tool names become part of public URLs
- **Document input schemas**: Help users understand required parameters
- **Handle Railway networking**: Use `railway.internal` URLs for internal communication

### What Happens After Registration
1. Hub creates route: `POST /my-awesome-tool/analyze`
2. Users can immediately call your endpoints via the hub
3. Hub forwards requests to your `internal_url` + endpoint path
4. Your service receives standard POST requests with JSON bodies

## Examples

### Image Processing Tool
**Registration:**
```json
{
  "name": "image-processor",
  "internal_url": "http://image-processor.railway.internal:3000",
  "endpoints": [
    {
      "path": "/resize",
      "method": "POST",
      "timeout": 120,
      "description": "Resize images",
      "input_schema": {
        "image": "base64 string",
        "width": "integer",
        "height": "integer"
      }
    }
  ]
}
```

**Usage:**
```bash
curl -X POST "hub.com/image-processor/resize" \
  -d '{"image": "data:image/jpeg;base64,/9j/4AA...", "width": 800, "height": 600}'
```

### Text Analysis Tool
**Registration:**
```json
{
  "name": "text-analyzer", 
  "internal_url": "http://text-analyzer.railway.internal:8000",
  "endpoints": [
    {
      "path": "/sentiment",
      "method": "POST",
      "timeout": 30,
      "description": "Analyze text sentiment",
      "input_schema": {
        "text": "string",
        "language": "string"
      }
    }
  ]
}
```

**Usage:**
```bash
curl -X POST "hub.com/text-analyzer/sentiment" \
  -d '{"text": "I love this product!", "language": "en"}'
```

## API Reference

### POST /register
Register a new service with the hub.

**Request Body:**
```json
{
  "name": "string",
  "internal_url": "string", 
  "endpoints": [
    {
      "path": "string",
      "method": "string",  // Optional, defaults to "POST"
      "timeout": 30,       // Optional, defaults to 30 seconds
      "description": "string",
      "input_schema": {
        "param_name": "type"
      }
    }
  ]
}
```

**Response:**
```json
{
  "status": "success",
  "message": "Service 'tool-name' registered",
  "service": { /* service data */ },
  "routes_created": 1
}
```

### GET /
View hub dashboard with all registered services and logs.

**Response:**
```json
{
  "hub_status": "running",
  "mode": "service_registration", 
  "services": { /* all registered services */ },
  "service_count": 3,
  "logs": [ /* recent activity logs */ ]
}
```

### POST /{service-name}/{endpoint}
Call a registered service endpoint (created dynamically).

**Request:** JSON body matching the service's `input_schema`

**Response:** Service's response or error message

### Error Responses
```json
{
  "error": "Internal service error",
  "details": "specific error message"
}
```