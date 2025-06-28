# MCP Dev Router

A development router for MCP (Model Context Protocol) servers that allows hot-swapping and dynamic management of backend servers without breaking client connections.

## Features

- **Hot-Swapping**: Restart/update MCP servers without disconnecting clients
- **Health Monitoring**: Automatic health checks and failover
- **True 1:1 Proxy**: Maintains exact MCP protocol compliance
- **Dynamic Management**: Add/remove backends at runtime
- **Graceful Degradation**: Returns 404s when backends are down instead of dropping connections

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Start the router
python mcp_router_final.py --port 8090 -b domain-mcp=http://localhost:8093

# Connect your MCP clients to http://localhost:8090 instead of the backend
```

## Usage

### Starting with Backends

```bash
# Single backend
python mcp_router_final.py --port 8090 -b my-server=http://localhost:8080

# Multiple backends
python mcp_router_final.py --port 8090 \
  -b domain-mcp=http://localhost:8080 \
  -b weather-mcp=http://localhost:8081
```

### Runtime Management

```bash
# Add a backend
curl -X POST http://localhost:8090/backends \
  -H "Content-Type: application/json" \
  -d '{"name": "new-server", "url": "http://localhost:8082"}'

# Remove a backend
curl -X DELETE http://localhost:8090/backends?name=new-server

# Check status
curl http://localhost:8090/status | jq
```

## How It Works

1. **Client Connection**: Clients connect to `/sse` on the router
2. **Health Monitoring**: Router continuously monitors backend health
3. **Request Routing**: Router proxies requests to healthy backends
4. **Session Management**: Router maintains session state during backend changes
5. **Failover**: When backends fail, router returns 404s but keeps connections alive

## Development

This router enables a smooth development workflow:

1. Start your MCP client connected to the router
2. Make changes to your MCP server
3. Restart the MCP server
4. Router automatically detects recovery and resumes routing
5. Client never disconnects or loses state

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  MCP Client │────▶│ MCP Router  │────▶│   Backend   │
│             │◀────│   (8090)    │◀────│ MCP Server  │
└─────────────┘     └─────────────┘     └─────────────┘
                           │
                           ▼
                    Health Checks
                    Every 30 seconds
```

## API Endpoints

- `GET /sse` - SSE endpoint for MCP clients
- `POST /messages/` - Message endpoint for MCP protocol
- `GET /status` - Router and backend status
- `GET /backends` - List backends
- `POST /backends` - Add backend
- `DELETE /backends?name=<name>` - Remove backend

## Management Tools

### Interactive TUI

```bash
# Launch interactive terminal UI
python router_manager.py

# Or via CLI
python router_cli.py tui
```

### Command Line Interface

```bash
# Show status
python router_cli.py status

# Add backend
python router_cli.py add my-server localhost:8080

# Remove backend  
python router_cli.py remove my-server

# List backends
python router_cli.py list
```

## Requirements

- Python 3.12+
- httpx
- starlette
- uvicorn
- click