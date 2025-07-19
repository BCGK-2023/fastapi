# Developer Integration Guide

## What is FastAPI-HUB

FastAPI-HUB is an API gateway that automatically creates public routes for your microtools. Instead of exposing each service publicly, you register with the hub and get instant public endpoints. When users call `fastapi-open-source-apis.up.railway.app/your-tool/endpoint`, the hub forwards the request to your internal service and returns the response.

## Integration Overview

### The Flow
1. **Your service starts** → calls hub's `/register` endpoint
2. **Hub creates routes** → `POST /your-tool/endpoint` becomes available publicly
3. **Users make requests** → hub forwards JSON to your internal service
4. **Your service responds** → hub returns your response to the user

### Networking Model
- **Internal**: Your service runs on `your-tool.railway.internal` (private)
- **Public**: Users call `fastapi-open-source-apis.up.railway.app/your-tool/endpoint` (public)
- **Registration**: Your service calls `fastapi-556cf929.railway.internal/register` (internal)

The hub handles all public exposure - your service only needs internal Railway networking.

## Quick Integration Guide

### 1. Add Registration to Your Startup

```javascript
// Node.js/Bun example
const registerWithHub = async () => {
  try {
    const response = await fetch("http://fastapi-556cf929.railway.internal/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: "my-tool",
        internal_url: "http://my-tool.railway.internal:3000",
        endpoints: [
          {
            path: "/process",
            description: "Process data",
            input_schema: {
              text: "string",
              options: "object"
            }
          }
        ]
      })
    });
    
    if (response.ok) {
      console.log("Successfully registered with hub");
    } else {
      console.error("Registration failed:", await response.text());
    }
  } catch (error) {
    console.error("Hub registration error:", error);
    // Continue running even if registration fails
  }
};

// Call on startup
registerWithHub();
```

### 2. Design Your Endpoints

Your endpoints should:
- Accept POST requests with JSON bodies
- Return JSON responses
- Handle errors gracefully

```javascript
app.post("/process", async (req, res) => {
  try {
    const { text, options } = req.body;
    
    // Validate input
    if (!text) {
      return res.status(400).json({ error: "Text is required" });
    }
    
    // Process data
    const result = await processText(text, options);
    
    // Return result
    res.json({ result, processed_at: new Date().toISOString() });
    
  } catch (error) {
    res.status(500).json({ 
      error: "Processing failed", 
      details: error.message 
    });
  }
});
```

### 3. Verify Registration

Check the hub dashboard at `https://fastapi-open-source-apis.up.railway.app/` to see if your service appears in the registered services list.

## Best Practices

### Registration
- **Register immediately on startup** - don't wait for first request
- **Handle registration failures gracefully** - your service should work even if hub is down
- **Use descriptive names** - they become part of public URLs
- **Register once** - don't re-register on every request

### Service Design
- **Accept JSON, return JSON** - hub forwards POST requests with JSON bodies
- **Validate inputs** - check required fields and types
- **Return structured errors** - use consistent error response format
- **Include helpful descriptions** - users see these in the hub dashboard

### Error Handling
```javascript
// Good error response
{
  "error": "Invalid input",
  "details": "Width must be between 1 and 5000 pixels",
  "code": "INVALID_WIDTH"
}

// Bad error response  
{
  "message": "Something went wrong"
}
```

### Service Naming
- Use kebab-case: `image-processor`, `text-analyzer`
- Be descriptive but concise: `pdf-converter` not `tool`
- Avoid conflicts: check hub dashboard before choosing names

## Common Patterns

### Startup Registration Pattern
```javascript
const startService = async () => {
  // Start your service first
  const server = app.listen(PORT, () => {
    console.log(`Service running on port ${PORT}`);
  });
  
  // Then register with hub
  await registerWithHub();
  
  // Handle graceful shutdown
  process.on('SIGTERM', () => {
    server.close(() => {
      console.log('Service shut down gracefully');
    });
  });
};

startService();
```

### Input Validation Pattern
```javascript
const validateInput = (body, schema) => {
  const errors = [];
  
  for (const [field, type] of Object.entries(schema)) {
    if (!(field in body)) {
      errors.push(`Missing required field: ${field}`);
    } else if (typeof body[field] !== type) {
      errors.push(`Field ${field} must be ${type}`);
    }
  }
  
  return errors;
};

app.post("/endpoint", (req, res) => {
  const errors = validateInput(req.body, {
    text: "string",
    count: "number"
  });
  
  if (errors.length > 0) {
    return res.status(400).json({ error: "Validation failed", details: errors });
  }
  
  // Process request...
});
```

### Logging Coordination
```javascript
// Log important events that complement hub logging
console.log(`Processing request: ${JSON.stringify(req.body).slice(0, 100)}...`);
console.log(`Request completed in ${duration}ms`);
console.log(`Error processing request: ${error.message}`);
```

## Troubleshooting

### Registration Not Working
1. **Check hub URL** - verify `fastapi-556cf929.railway.internal` is reachable
2. **Verify JSON format** - ensure registration payload matches expected schema
3. **Check hub logs** - visit hub dashboard to see registration attempts
4. **Network connectivity** - ensure your service can reach internal Railway network

### Service Not Receiving Requests
1. **Verify registration** - check hub dashboard shows your service
2. **Check internal URL** - ensure `your-service.railway.internal:PORT` is correct
3. **Test directly** - try calling your service directly from another Railway service
4. **Check endpoint paths** - ensure they match what you registered

### Common Registration Errors
```javascript
// Wrong internal URL format
"internal_url": "your-service.railway.internal"  // Missing http://

// Incorrect endpoint paths  
"path": "process"  // Missing leading slash, should be "/process"

// Invalid schema types
"input_schema": { "count": "int" }  // Should be "integer"
```

### Testing Your Integration
```bash
# Test registration endpoint directly
curl -X POST "http://fastapi-556cf929.railway.internal/register" \
  -H "Content-Type: application/json" \
  -d '{"name":"test","internal_url":"http://test.railway.internal:3000","endpoints":[{"path":"/test","description":"Test","input_schema":{"data":"string"}}]}'

# Test your service directly
curl -X POST "http://your-service.railway.internal:3000/endpoint" \
  -H "Content-Type: application/json" \
  -d '{"test":"data"}'

# Test through the hub
curl -X POST "https://fastapi-open-source-apis.up.railway.app/your-service/endpoint" \
  -H "Content-Type: application/json" \
  -d '{"test":"data"}'
```

Remember: Your service should work independently of the hub. Registration is just for public exposure - if the hub is down, your service should continue operating normally.