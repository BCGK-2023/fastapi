from fastapi import FastAPI, Request
from pydantic import BaseModel
import httpx
import json
import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional
import pytz

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="FastAPI-HUB", description="Self-describing microservices hub")

# Service registry and logs
services_registry: Dict[str, Dict[str, Any]] = {}
registration_logs: List[Dict[str, Any]] = []
MAX_LOGS = 100

class EndpointSchema(BaseModel):
    path: str
    method: str = "POST"  # Default to POST for backward compatibility
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

def check_and_update_service_statuses():
    """Check all services and update their status based on last_seen"""
    uk_tz = pytz.timezone('Europe/London')
    now_uk = datetime.now(uk_tz)
    
    stale_threshold = timedelta(minutes=15)  # 3 missed heartbeats
    remove_threshold = timedelta(hours=1)    # Remove after 1 hour
    
    staled_services = []
    removed_services = []
    
    services_to_remove = []
    
    for service_name, service_data in services_registry.items():
        last_seen_str = service_data.get('last_seen')
        if not last_seen_str:
            continue
            
        try:
            # Parse the last_seen timestamp (assuming it's in ISO format)
            last_seen = datetime.fromisoformat(last_seen_str.replace('Z', '+00:00'))
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=timezone.utc)
            last_seen_uk = last_seen.astimezone(uk_tz)
            
            time_diff = now_uk - last_seen_uk
            
            # Check if service should be removed (1 hour)
            if time_diff > remove_threshold:
                services_to_remove.append(service_name)
                removed_services.append(service_name)
                continue
            
            # Check if service should be marked as stale (15 minutes)
            if time_diff > stale_threshold:
                if service_data.get('status') != 'stale':
                    service_data['status'] = 'stale'
                    service_data['marked_stale_at'] = now_uk.isoformat()
                    staled_services.append(service_name)
            else:
                # Service is active, ensure it's not marked as stale
                if service_data.get('status') == 'stale':
                    service_data['status'] = 'active'
                    if 'marked_stale_at' in service_data:
                        del service_data['marked_stale_at']
                        
        except Exception as e:
            log_message("ERROR", f"Error processing service {service_name} timestamps: {e}")
    
    # Remove services that exceeded the remove threshold
    for service_name in services_to_remove:
        del services_registry[service_name]
    
    # Log the changes
    if staled_services:
        log_message("WARNING", f"Marked services as stale (missed heartbeats): {', '.join(staled_services)}")
    
    if removed_services:
        log_message("INFO", f"Removed services (1+ hour since last heartbeat): {', '.join(removed_services)}")
    
    return {
        "staled": staled_services,
        "removed": removed_services
    }

async def create_dynamic_route(service_name: str, endpoint_path: str, internal_url: str, input_schema: Dict[str, str], method: str = "POST"):
    """Create a dynamic route for a registered service endpoint"""
    route_path = f"/{service_name}{endpoint_path}"
    
    async def route_handler(request: Request):
        try:
            # Get request body (only for methods that typically have bodies)
            body = {}
            if method.upper() in ["POST", "PUT", "PATCH"]:
                body = await request.json() if await request.body() else {}
            
            # Log the incoming request
            log_message("INFO", f"Route called: {method.upper()} {route_path} with body: {truncate_body(body)}")
            log_message("INFO", f"Forwarding to: {internal_url}{endpoint_path}")
            
            # Forward request to internal service
            async with httpx.AsyncClient(timeout=30) as client:
                request_kwargs = {
                    "headers": {"Content-Type": "application/json"} if body else {}
                }
                
                if method.upper() == "GET":
                    response = await client.get(f"{internal_url}{endpoint_path}", **request_kwargs)
                elif method.upper() == "POST":
                    response = await client.post(f"{internal_url}{endpoint_path}", json=body, **request_kwargs)
                elif method.upper() == "PUT":
                    response = await client.put(f"{internal_url}{endpoint_path}", json=body, **request_kwargs)
                elif method.upper() == "DELETE":
                    response = await client.delete(f"{internal_url}{endpoint_path}", **request_kwargs)
                elif method.upper() == "PATCH":
                    response = await client.patch(f"{internal_url}{endpoint_path}", json=body, **request_kwargs)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")
                
                # Log the response
                log_message("INFO", f"Response received: {response.status_code} from {internal_url}{endpoint_path}")
                
                # Return the response
                return response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text
                
        except Exception as e:
            log_message("ERROR", f"Error forwarding request to {internal_url}{endpoint_path}: {str(e)}")
            return {"error": "Internal service error", "details": str(e)}
    
    # Add the route to FastAPI with the correct method
    if method.upper() == "GET":
        app.get(route_path)(route_handler)
    elif method.upper() == "POST":
        app.post(route_path)(route_handler)
    elif method.upper() == "PUT":
        app.put(route_path)(route_handler)
    elif method.upper() == "DELETE":
        app.delete(route_path)(route_handler)
    elif method.upper() == "PATCH":
        app.patch(route_path)(route_handler)
    else:
        log_message("ERROR", f"Unsupported HTTP method for route creation: {method}")
        return
    
    # Log route creation
    log_message("INFO", f"Created route: {method.upper()} {route_path} -> {internal_url}{endpoint_path}")
    log_message("INFO", f"Route expects input: {input_schema}")

@app.post("/register")
async def register_service(service: ServiceRegistration):
    """Register a service with the hub"""
    try:
        # Check and update all service statuses before processing this registration
        status_changes = check_and_update_service_statuses()
        
        uk_tz = pytz.timezone('Europe/London')
        now_uk = datetime.now(uk_tz)
        
        # Check if this is a re-registration
        is_reregistration = service.name in services_registry
        
        # Validate internal_url for common issues
        if ' ' in service.internal_url:
            log_message("WARNING", f"Invalid hostname in internal_url: '{service.internal_url}' - contains spaces. This will cause connection failures.")
        
        # Store service info with timestamp
        service_data = {
            "name": service.name,
            "internal_url": service.internal_url,
            "endpoints": [endpoint.dict() for endpoint in service.endpoints],
            "last_seen": now_uk.isoformat(),
            "status": "active"
        }
        
        # Keep original registration time if re-registering
        if is_reregistration:
            service_data["registered_at"] = services_registry[service.name].get("registered_at", now_uk.isoformat())
        else:
            service_data["registered_at"] = now_uk.isoformat()
        
        services_registry[service.name] = service_data
        
        # Only log and create routes for new registrations
        if not is_reregistration:
            log_message("INFO", f"Service '{service.name}' registered successfully")
            
            # Create dynamic routes for each endpoint
            for endpoint in service.endpoints:
                await create_dynamic_route(
                    service.name, 
                    endpoint.path, 
                    service.internal_url,
                    endpoint.input_schema,
                    endpoint.method
                )
        else:
            # For re-registration, just update last_seen (no logging or route creation)
            pass
        
        return {
            "status": "success",
            "message": f"Service '{service.name}' {'re-registered' if is_reregistration else 'registered'}",
            "service": service_data,
            "routes_created": len(service.endpoints) if not is_reregistration else 0,
            "status_changes": status_changes
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

@app.get("/test/network")
async def test_network():
    """Test Railway internal networking and external connectivity"""
    import subprocess
    import asyncio
    
    results = {
        "timestamp": datetime.now().isoformat(),
        "tests": {}
    }
    
    # Test 1: Hub internal health check
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get("http://fastapi-556cf929.railway.internal/")
            results["tests"]["hub_internal_access"] = {
                "status": "success",
                "response_code": response.status_code,
                "accessible": True
            }
    except Exception as e:
        results["tests"]["hub_internal_access"] = {
            "status": "failed",
            "error": str(e),
            "accessible": False
        }
    
    # Test 2: External internet connectivity
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get("https://httpbin.org/ip")
            results["tests"]["external_internet"] = {
                "status": "success",
                "response_code": response.status_code,
                "accessible": True,
                "response": response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text[:100]
            }
    except Exception as e:
        results["tests"]["external_internet"] = {
            "status": "failed",
            "error": str(e),
            "accessible": False
        }
    
    # Test 3: DNS resolution
    try:
        process = await asyncio.create_subprocess_exec(
            "nslookup", "fastapi-556cf929.railway.internal",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        results["tests"]["dns_resolution"] = {
            "status": "success" if process.returncode == 0 else "failed",
            "return_code": process.returncode,
            "stdout": stdout.decode()[:500],
            "stderr": stderr.decode()[:200] if stderr else ""
        }
    except Exception as e:
        results["tests"]["dns_resolution"] = {
            "status": "failed",
            "error": str(e)
        }
    
    return results

@app.get("/")
async def dashboard():
    """FastAPI-HUB Dashboard - shows registered services and logs"""
    # Update service statuses when dashboard is accessed
    status_changes = check_and_update_service_statuses()
    
    # Categorize services by status
    active_services = {name: data for name, data in services_registry.items() if data.get('status') != 'stale'}
    stale_services = {name: data for name, data in services_registry.items() if data.get('status') == 'stale'}
    
    return {
        "hub_status": "running",
        "mode": "service_registration_with_heartbeat",
        "services": {
            "active": active_services,
            "stale": stale_services,
            "total_count": len(services_registry),
            "active_count": len(active_services),
            "stale_count": len(stale_services)
        },
        "heartbeat_info": {
            "interval": "Every 5 minutes (UK time: :00, :05, :10, :15, etc.)",
            "stale_after": "15 minutes (3 missed heartbeats)",
            "removed_after": "1 hour"
        },
        "logs": registration_logs[-20:],  # Show last 20 logs
        "status_changes": status_changes,
        "endpoints": {
            "register": "POST /register - Register a service (also used for heartbeat)",
            "dashboard": "GET / - View this dashboard",
            "network_test": "GET /test/network - Test Railway networking"
        }
    }