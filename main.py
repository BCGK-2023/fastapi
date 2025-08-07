from fastapi import FastAPI, Request
from pydantic import BaseModel
import httpx
import json
import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional
import pytz
import asyncio
import random
from enum import Enum

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="FastAPI-HUB", description="Self-describing microservices hub")

# Service registry and logs
services_registry: Dict[str, Dict[str, Any]] = {}
registration_logs: List[Dict[str, Any]] = []
MAX_LOGS = 100

# Circuit breaker states and registry
class CircuitState(Enum):
    CLOSED = "closed"      # Normal operation
    OPEN = "open"         # Blocking requests
    HALF_OPEN = "half_open"  # Testing if service recovered

class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.timeout = timeout  # seconds to wait before trying again
        self.failure_count = 0
        self.last_failure_time = None
        self.state = CircuitState.CLOSED
    
    def can_execute(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True
        elif self.state == CircuitState.OPEN:
            if self.last_failure_time and datetime.now() - self.last_failure_time > timedelta(seconds=self.timeout):
                self.state = CircuitState.HALF_OPEN
                return True
            return False
        else:  # HALF_OPEN
            return True
    
    def record_success(self):
        self.failure_count = 0
        self.state = CircuitState.CLOSED
    
    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = datetime.now()
        
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN

circuit_breakers: Dict[str, CircuitBreaker] = {}

class EndpointSchema(BaseModel):
    path: str
    method: str = "POST"  # Default to POST for backward compatibility
    description: str
    input_schema: Dict[str, str]
    timeout: int = 30  # Default timeout in seconds
    connect_timeout: int = 10  # Connection timeout
    read_timeout: int = 300    # Read timeout for long operations
    max_retries: int = 3       # Number of retry attempts

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

async def health_check_service(internal_url: str) -> bool:
    """Check if service is healthy before forwarding requests"""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            # Try health endpoint first, fallback to base URL
            for path in ["/health", "/", ""]:
                try:
                    response = await client.get(f"{internal_url}{path}")
                    if response.status_code < 500:  # 2xx, 3xx, 4xx are considered "reachable"
                        return True
                except:
                    continue
        return False
    except:
        return False

async def forward_with_retry(internal_url: str, endpoint_path: str, method: str, body: dict, 
                           connect_timeout: int, read_timeout: int, max_retries: int = 3):
    """Forward request with exponential backoff retry"""
    
    timeout_config = httpx.Timeout(
        connect=connect_timeout,
        read=read_timeout,
        write=30.0,
        pool=10.0
    )
    
    for attempt in range(max_retries + 1):  # 0, 1, 2, 3
        try:
            async with httpx.AsyncClient(timeout=timeout_config) as client:
                request_kwargs = {"headers": {"Content-Type": "application/json"} if body else {}}
                
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
                
                response.raise_for_status()  # Raise for 4xx/5xx
                log_message("INFO", f"Response received: {response.status_code} from {internal_url}{endpoint_path}")
                return response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text
                
        except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError, httpx.NetworkError) as e:
            if attempt == max_retries:
                log_message("ERROR", f"All {max_retries + 1} attempts failed for {internal_url}{endpoint_path}: {str(e)}")
                raise
            
            # Exponential backoff: 1s, 2s, 4s + jitter
            delay = (2 ** attempt) + random.uniform(0, 1)
            log_message("WARNING", f"Attempt {attempt + 1} failed for {internal_url}{endpoint_path}, retrying in {delay:.1f}s: {str(e)}")
            await asyncio.sleep(delay)

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

async def create_dynamic_route(service_name: str, endpoint_path: str, internal_url: str, input_schema: Dict[str, str], 
                              method: str = "POST", timeout: int = 30, connect_timeout: int = 10, 
                              read_timeout: int = 300, max_retries: int = 3):
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
            
            # Circuit breaker check
            service_key = f"{service_name}{endpoint_path}"
            if service_key not in circuit_breakers:
                circuit_breakers[service_key] = CircuitBreaker()
            
            breaker = circuit_breakers[service_key]
            
            if not breaker.can_execute():
                log_message("WARNING", f"Circuit breaker OPEN for {service_key}")
                return {
                    "error": "Service temporarily unavailable", 
                    "circuit_breaker": "open",
                    "retry_after": breaker.timeout
                }
            
            # Health check before forwarding
            if not await health_check_service(internal_url):
                log_message("WARNING", f"Health check failed for {internal_url}")
                breaker.record_failure()
                return {"error": "Service health check failed", "service": service_name}
            
            # Forward request with retry logic
            try:
                response = await forward_with_retry(
                    internal_url, endpoint_path, method, body, 
                    connect_timeout, read_timeout, max_retries
                )
                breaker.record_success()
                return response
                
            except Exception as e:
                breaker.record_failure()
                raise
                
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
    log_message("INFO", f"Created route: {method.upper()} {route_path} -> {internal_url}{endpoint_path} (connect: {connect_timeout}s, read: {read_timeout}s, retries: {max_retries})")
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
                    endpoint.method,
                    endpoint.timeout,
                    endpoint.connect_timeout,
                    endpoint.read_timeout,
                    endpoint.max_retries
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

async def periodic_health_checks():
    """Background task to check all services health"""
    while True:
        try:
            for service_name, service_data in services_registry.items():
                if service_data.get('status') == 'active':
                    is_healthy = await health_check_service(service_data['internal_url'])
                    if not is_healthy:
                        log_message("WARNING", f"Service {service_name} failed periodic health check")
        except Exception as e:
            log_message("ERROR", f"Error in periodic health checks: {e}")
        
        await asyncio.sleep(60)  # Check every minute

@app.on_event("startup")
async def startup_event():
    """Initialize the hub"""
    log_message("INFO", "FastAPI-HUB starting up - service registration mode")
    # Start background health checks
    asyncio.create_task(periodic_health_checks())

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