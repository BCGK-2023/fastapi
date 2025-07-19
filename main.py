from fastapi import FastAPI
import httpx
import asyncio
import os
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="FastAPI-HUB", description="Self-describing microservices hub")

# Service registry and dashboard data
services_registry: Dict[str, Dict[str, Any]] = {}
discovery_logs: List[Dict[str, Any]] = []
next_scan_time: Optional[float] = None
MAX_LOGS = 100

# Configuration
RAILWAY_API_TOKEN = "97a99c31-dd6b-4886-b23f-9d8d7f66517a"
DISCOVERY_INTERVAL_SECONDS = int(os.getenv("HUB_DISCOVERY_INTERVAL_SECONDS", "120"))
DISCOVERY_TIMEOUT_SECONDS = int(os.getenv("HUB_DISCOVERY_TIMEOUT_SECONDS", "3"))
COMMON_SERVICE_NAMES = ["api", "auth", "user", "backend", "frontend", "web", "app", "service"]

def log_message(level: str, message: str):
    """Custom logging function that stores logs in memory and logs to console"""
    global discovery_logs
    
    # Add to in-memory logs
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "level": level,
        "message": message
    }
    discovery_logs.append(log_entry)
    
    # Keep only last MAX_LOGS entries
    if len(discovery_logs) > MAX_LOGS:
        discovery_logs = discovery_logs[-MAX_LOGS:]
    
    # Also log to console
    if level == "INFO":
        logger.info(message)
    elif level == "WARNING":
        logger.warning(message)
    elif level == "DEBUG":
        logger.debug(message)

async def query_railway_services() -> List[str]:
    """Query Railway GraphQL API for actual service names"""
    try:
        headers = {
            'Authorization': f'Bearer {RAILWAY_API_TOKEN}',
            'Content-Type': 'application/json'
        }
        
        query = """
        query me {
          me {
            projects {
              edges {
                node {
                  id
                  name
                  services {
                    edges {
                      node {
                        id
                        name
                      }
                    }
                  }
                }
              }
            }
          }
        }
        """
        
        async with httpx.AsyncClient(timeout=DISCOVERY_TIMEOUT_SECONDS) as client:
            response = await client.post(
                'https://backboard.railway.com/graphql/v2',
                headers=headers,
                json={'query': query}
            )
            
            if response.status_code == 200:
                data = response.json()
                service_names = []
                
                for project in data.get('data', {}).get('me', {}).get('projects', {}).get('edges', []):
                    for service in project['node'].get('services', {}).get('edges', []):
                        service_names.append(service['node']['name'])
                
                log_message("INFO", f"GraphQL API found services: {service_names}")
                return service_names
            else:
                log_message("WARNING", f"GraphQL API failed with status {response.status_code}")
                return []
                
    except Exception as e:
        log_message("WARNING", f"GraphQL API error: {e}")
        return []

async def get_service_names() -> List[str]:
    """Get service names via GraphQL API + common name fallback"""
    # Try GraphQL first
    graphql_services = await query_railway_services()
    
    # Add common names as fallback
    all_names = list(set(graphql_services + COMMON_SERVICE_NAMES))
    
    log_message("INFO", f"Checking service names: {all_names}")
    return all_names

async def probe_service_init(service_name: str) -> Optional[Dict[str, Any]]:
    """Probe a service's /init endpoint"""
    url = f"http://{service_name}.railway.internal"
    
    try:
        async with httpx.AsyncClient(timeout=DISCOVERY_TIMEOUT_SECONDS) as client:
            # First check if service is reachable
            health_response = await client.get(f"{url}/")
            if health_response.status_code != 200:
                return None
                
            # Then try /init endpoint
            init_response = await client.get(f"{url}/init")
            if init_response.status_code == 200:
                init_data = init_response.json()
                log_message("INFO", f"Service '{service_name}' has /init endpoint")
                return {
                    "name": service_name,
                    "url": url,
                    "endpoints": init_data.get("endpoints", []),
                    "timestamp": datetime.now().isoformat()
                }
            else:
                log_message("INFO", f"Found '{service_name}' but no /init endpoint available")
                return None
                
    except Exception as e:
        log_message("DEBUG", f"Service '{service_name}' not reachable: {e}")
        return None

async def discover_services():
    """Main service discovery function"""
    log_message("INFO", "Starting service discovery...")
    
    service_names = await get_service_names()
    discovered_count = 0
    
    for service_name in service_names:
        # Skip self
        if service_name == os.getenv("RAILWAY_SERVICE_NAME", "fastapi-hub"):
            continue
            
        service_info = await probe_service_init(service_name)
        if service_info:
            services_registry[service_name] = service_info
            discovered_count += 1
    
    log_message("INFO", f"Discovery complete. Found {discovered_count} services with /init endpoints")

async def cleanup_stale_services():
    """Remove services that are no longer responsive"""
    stale_services = []
    
    for service_name, service_info in list(services_registry.items()):
        try:
            url = service_info["url"]
            async with httpx.AsyncClient(timeout=DISCOVERY_TIMEOUT_SECONDS) as client:
                response = await client.get(f"{url}/")
                if response.status_code != 200:
                    stale_services.append(service_name)
        except Exception:
            stale_services.append(service_name)
    
    for service_name in stale_services:
        del services_registry[service_name]
        log_message("INFO", f"Removed stale service: {service_name}")

async def periodic_discovery():
    """Background task for periodic service discovery"""
    global next_scan_time
    
    # Initial discovery
    await discover_services()
    
    # Burst mode - every 30 seconds for first 5 minutes
    burst_end_time = asyncio.get_event_loop().time() + 300  # 5 minutes
    
    while asyncio.get_event_loop().time() < burst_end_time:
        next_scan_time = asyncio.get_event_loop().time() + 30
        await asyncio.sleep(30)
        await discover_services()
        await cleanup_stale_services()
    
    # Steady state - every 2 minutes (or configured interval)
    while True:
        next_scan_time = asyncio.get_event_loop().time() + DISCOVERY_INTERVAL_SECONDS
        await asyncio.sleep(DISCOVERY_INTERVAL_SECONDS)
        await discover_services()
        await cleanup_stale_services()

@app.on_event("startup")
async def startup_event():
    """Start background discovery task on startup"""
    log_message("INFO", "FastAPI-HUB starting up...")
    asyncio.create_task(periodic_discovery())

@app.get("/")
async def dashboard():
    """FastAPI-HUB Dashboard - shows services, logs, and next scan time"""
    current_time = asyncio.get_event_loop().time()
    
    # Calculate seconds until next scan
    seconds_until_next = 0
    if next_scan_time:
        seconds_until_next = max(0, int(next_scan_time - current_time))
    
    return {
        "hub_status": "running",
        "next_scan_in_seconds": seconds_until_next,
        "services": services_registry,
        "service_count": len(services_registry),
        "logs": discovery_logs[-20:],  # Show last 20 logs
        "discovery_interval": DISCOVERY_INTERVAL_SECONDS
    }