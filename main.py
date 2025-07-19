from fastapi import FastAPI, Request
from pydantic import BaseModel
import httpx
import json
import os
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="FastAPI-HUB", description="Self-describing microservices hub")

# Service registry and logs
services_registry: Dict[str, Dict[str, Any]] = {}
registration_logs: List[Dict[str, Any]] = []
MAX_LOGS = 100

class EndpointSchema(BaseModel):
    path: str
    description: str
    input_schema: Dict[str, str]

class ServiceRegistration(BaseModel):
    name: str
    internal_url: str
    endpoints: List[EndpointSchema]

def log_message(level: str, message: str):
    """Custom logging function that stores logs in memory and logs to console"""
    global registration_logs
    
    # Add to in-memory logs
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "level": level,
        "message": message
    }
    registration_logs.append(log_entry)
    
    # Keep only last MAX_LOGS entries
    if len(registration_logs) > MAX_LOGS:
        registration_logs = registration_logs[-MAX_LOGS:]
    
    # Also log to console
    if level == "INFO":
        logger.info(message)
    elif level == "WARNING":
        logger.warning(message)
    elif level == "DEBUG":
        logger.debug(message)

def truncate_body(body: Any, max_length: int = 200) -> str:
    """Truncate large request/response bodies for logging"""
    try:
        if isinstance(body, dict):
            body_str = json.dumps(body)
        else:
            body_str = str(body)
        
        if len(body_str) > max_length:
            return body_str[:max_length] + "... [truncated]"
        return body_str
    except:
        return "[unable to serialize body]"

async def create_dynamic_route(service_name: str, endpoint_path: str, internal_url: str, input_schema: Dict[str, str]):
    """Create a dynamic route for a registered service endpoint"""
    route_path = f"/{service_name}{endpoint_path}"
    
    async def route_handler(request: Request):
        try:
            # Get request body
            body = await request.json() if await request.body() else {}
            
            # Log the incoming request
            log_message("INFO", f"Route called: POST {route_path} with body: {truncate_body(body)}")
            log_message("INFO", f"Forwarding to: {internal_url}{endpoint_path}")
            
            # Forward request to internal service
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"{internal_url}{endpoint_path}",
                    json=body,
                    headers={"Content-Type": "application/json"}
                )
                
                # Log the response
                log_message("INFO", f"Response received: {response.status_code} from {internal_url}{endpoint_path}")
                
                # Return the response
                return response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text
                
        except Exception as e:
            log_message("ERROR", f"Error forwarding request to {internal_url}{endpoint_path}: {str(e)}")
            return {"error": "Internal service error", "details": str(e)}
    
    # Add the route to FastAPI
    app.post(route_path)(route_handler)
    
    # Log route creation
    log_message("INFO", f"Created route: POST {route_path} -> {internal_url}{endpoint_path}")
    log_message("INFO", f"Route expects input: {input_schema}")

@app.post("/register")
async def register_service(service: ServiceRegistration):
    """Register a service with the hub"""
    try:
        # Store service info with timestamp
        service_data = {
            "name": service.name,
            "internal_url": service.internal_url,
            "endpoints": [endpoint.dict() for endpoint in service.endpoints],
            "registered_at": datetime.now().isoformat(),
            "last_seen": datetime.now().isoformat()
        }
        
        services_registry[service.name] = service_data
        log_message("INFO", f"Service '{service.name}' registered successfully")
        
        # Create dynamic routes for each endpoint
        for endpoint in service.endpoints:
            await create_dynamic_route(
                service.name, 
                endpoint.path, 
                service.internal_url,
                endpoint.input_schema
            )
        
        return {
            "status": "success",
            "message": f"Service '{service.name}' registered",
            "service": service_data,
            "routes_created": len(service.endpoints)
        }
        
    except Exception as e:
        log_message("ERROR", f"Failed to register service '{service.name}': {e}")
        return {
            "status": "error",
            "message": str(e)
        }

@app.on_event("startup")
async def startup_event():
    """Initialize the hub"""
    log_message("INFO", "FastAPI-HUB starting up - service registration mode")

@app.get("/")
async def dashboard():
    """FastAPI-HUB Dashboard - shows registered services and logs"""
    return {
        "hub_status": "running",
        "mode": "service_registration",
        "services": services_registry,
        "service_count": len(services_registry),
        "logs": registration_logs[-20:],  # Show last 20 logs
        "endpoints": {
            "register": "POST /register - Register a service",
            "dashboard": "GET / - View this dashboard"
        }
    }