from fastapi import FastAPI
from pydantic import BaseModel
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
        
        return {
            "status": "success",
            "message": f"Service '{service.name}' registered",
            "service": service_data
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