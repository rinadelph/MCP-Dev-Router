#!/usr/bin/env python3
"""
MCP Router Final - Simple working version with proper resource management
"""

import asyncio
import json
import logging
from typing import Dict, Optional, Any
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

import click
import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.requests import Request
from starlette.responses import StreamingResponse, JSONResponse, Response

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ServerStatus(Enum):
    """Status of a backend MCP server"""
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    CHECKING = "checking"


@dataclass
class BackendServer:
    """Represents a backend MCP server"""
    name: str
    url: str
    status: ServerStatus = ServerStatus.CHECKING
    last_check: Optional[datetime] = None
    last_healthy: Optional[datetime] = None
    consecutive_failures: int = 0


class MCPRouter:
    """Simple MCP router that acts as a transparent proxy"""
    
    def __init__(self, health_check_interval: int = 30):
        self.backends: Dict[str, BackendServer] = {}
        self.health_check_interval = health_check_interval
        self._health_check_task: Optional[asyncio.Task] = None
        
    async def add_backend(self, name: str, url: str) -> None:
        """Add a new backend server"""
        self.backends[name] = BackendServer(name=name, url=url)
        logger.info(f"Added backend server: {name} at {url}")
        
    async def remove_backend(self, name: str) -> None:
        """Remove a backend server"""
        if name in self.backends:
            del self.backends[name]
            logger.info(f"Removed backend server: {name}")
            
    async def start(self) -> None:
        """Start the router and health check loop"""
        self._health_check_task = asyncio.create_task(self._health_check_loop())
        logger.info("MCP Router started")
        
    async def stop(self) -> None:
        """Stop the router"""
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
        logger.info("MCP Router stopped")
        
    async def _health_check_loop(self) -> None:
        """Continuously check health of backend servers"""
        while True:
            await self._check_all_backends()
            await asyncio.sleep(self.health_check_interval)
            
    async def _check_all_backends(self) -> None:
        """Check health of all backend servers"""
        tasks = [self._check_backend_health(backend) for backend in self.backends.values()]
        await asyncio.gather(*tasks, return_exceptions=True)
        
    async def _check_backend_health(self, backend: BackendServer) -> None:
        """Check health of a single backend server"""
        backend.last_check = datetime.now()
        
        try:
            async with httpx.AsyncClient() as client:
                async with client.stream(
                    "GET",
                    f"{backend.url}/sse",
                    timeout=10.0,
                    headers={"Accept": "text/event-stream"}
                ) as response:
                    
                    if response.status_code != 200:
                        raise Exception(f"Non-200 status code: {response.status_code}")
                    
                    # Read just enough to see the endpoint event
                    lines_read = 0
                    async for line in response.aiter_lines():
                        if line == "event: endpoint":
                            backend.status = ServerStatus.HEALTHY
                            backend.last_healthy = datetime.now()
                            backend.consecutive_failures = 0
                            logger.debug(f"Backend {backend.name} is healthy")
                            return
                        lines_read += 1
                        if lines_read > 5:  # Don't read too many lines
                            break
                    
                    raise Exception("No endpoint event found")
                    
        except Exception as e:
            backend.consecutive_failures += 1
            if backend.consecutive_failures >= 3:
                backend.status = ServerStatus.UNHEALTHY
                logger.warning(f"Backend {backend.name} is unhealthy: {e}")
            else:
                logger.debug(f"Backend {backend.name} health check failed (attempt {backend.consecutive_failures}): {e}")
                
    def get_healthy_backend(self, preferred: Optional[str] = None) -> Optional[BackendServer]:
        """Get a healthy backend server"""
        if preferred and preferred in self.backends:
            backend = self.backends[preferred]
            if backend.status == ServerStatus.HEALTHY:
                return backend
                
        # Find any healthy backend
        for backend in self.backends.values():
            if backend.status == ServerStatus.HEALTHY:
                return backend
                
        return None
        
    async def proxy_sse(self, request: Request, backend_name: Optional[str] = None) -> StreamingResponse:
        """Proxy SSE connection with 1:1 passthrough"""
        backend = self.get_healthy_backend(backend_name)
        
        if not backend:
            # No healthy backends - return 404 in SSE format
            return StreamingResponse(
                self._error_stream("No healthy MCP servers available"),
                media_type="text/event-stream",
                status_code=404
            )
            
        logger.info(f"Proxying SSE to backend: {backend.name}")
        
        async def stream_from_backend():
            """Stream data from backend to client"""
            try:
                async with httpx.AsyncClient() as client:
                    async with client.stream(
                        "GET",
                        f"{backend.url}/sse",
                        headers={k: v for k, v in request.headers.items() if k.lower() != 'host'},
                        timeout=None
                    ) as response:
                        
                        if response.status_code != 200:
                            async for chunk in self._error_stream("Backend returned error"):
                                yield chunk
                            return
                            
                        # Stream the response directly
                        async for chunk in response.aiter_bytes():
                            yield chunk
                            
            except Exception as e:
                logger.error(f"Error streaming from backend {backend.name}: {e}")
                async for chunk in self._error_stream("Connection to backend lost"):
                    yield chunk
                    
        return StreamingResponse(
            stream_from_backend(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Backend-Server": backend.name
            }
        )
            
    async def proxy_messages(self, request: Request) -> Response:
        """Proxy POST messages with 1:1 passthrough"""
        # Get session_id to determine backend (for now, just use any healthy backend)
        backend = self.get_healthy_backend()
        if not backend:
            return JSONResponse(
                {"error": "No healthy backends available"},
                status_code=404
            )
            
        try:
            # Get the raw body
            body = await request.body()
            
            async with httpx.AsyncClient() as client:
                # Forward the exact request to the backend
                response = await client.post(
                    f"{backend.url}/messages/",
                    params=dict(request.query_params),
                    headers={k: v for k, v in request.headers.items() if k.lower() != 'host'},
                    content=body
                )
                
                # Return the exact response
                return Response(
                    content=response.content,
                    status_code=response.status_code,
                    headers={k: v for k, v in dict(response.headers).items() 
                            if k.lower() not in ['content-length', 'transfer-encoding']}
                )
            
        except Exception as e:
            logger.error(f"Failed to proxy message to backend {backend.name}: {e}")
            return JSONResponse(
                {"error": "Failed to connect to backend"},
                status_code=502
            )
            
    async def _error_stream(self, message: str):
        """Generate error stream in SSE format"""
        yield f"event: error\ndata: {message}\n\n".encode()
        
    async def get_status(self) -> Dict[str, Any]:
        """Get router status"""
        return {
            "router": "healthy",
            "backends": {
                name: {
                    "url": backend.url,
                    "status": backend.status.value,
                    "last_check": backend.last_check.isoformat() if backend.last_check else None,
                    "last_healthy": backend.last_healthy.isoformat() if backend.last_healthy else None,
                    "consecutive_failures": backend.consecutive_failures
                }
                for name, backend in self.backends.items()
            }
        }


# Global router instance
router = MCPRouter()


async def handle_sse(request: Request):
    """Handle SSE connections"""
    backend_name = request.query_params.get("backend")
    return await router.proxy_sse(request, backend_name)


async def handle_messages(request: Request):
    """Handle message posts"""
    return await router.proxy_messages(request)


async def handle_status(request: Request):
    """Handle status endpoint"""
    status = await router.get_status()
    return JSONResponse(status)


async def handle_backends(request: Request):
    """Handle backend management"""
    if request.method == "POST":
        data = await request.json()
        await router.add_backend(data["name"], data["url"])
        return JSONResponse({"status": "added"})
    elif request.method == "DELETE":
        name = request.query_params.get("name")
        await router.remove_backend(name)
        return JSONResponse({"status": "removed"})
    else:
        return JSONResponse(
            {name: backend.url for name, backend in router.backends.items()}
        )


# Create Starlette app
app = Starlette(
    debug=True,
    routes=[
        Route("/sse", endpoint=handle_sse, methods=["GET"]),
        Route("/messages/", endpoint=handle_messages, methods=["POST"]),
        Route("/status", endpoint=handle_status),
        Route("/backends", endpoint=handle_backends, methods=["GET", "POST", "DELETE"]),
    ],
    on_startup=[router.start],
    on_shutdown=[router.stop]
)


@click.command()
@click.option("--port", default=8090, help="Port to listen on")
@click.option("--health-interval", default=30, help="Health check interval in seconds")
@click.option("--backend", "-b", multiple=True, help="Backend servers in format name=url")
def main(port: int, health_interval: int, backend: tuple):
    """MCP Router Final - Working transparent proxy"""
    
    # Add backends from command line
    async def setup_backends():
        for b in backend:
            if "=" in b:
                name, url = b.split("=", 1)
                await router.add_backend(name, url)
                
    # Run setup before starting server
    asyncio.run(setup_backends())
    
    # Update health check interval
    router.health_check_interval = health_interval
    
    # Run server
    logger.info(f"Starting MCP Router Final on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()