#!/usr/bin/env python3
"""
MCP Router CLI - Simple command-line interface for managing router backends
"""

import asyncio
import json
from typing import Optional

import click
import httpx


class RouterCLI:
    """CLI for MCP Router management"""
    
    def __init__(self, router_url: str = "http://localhost:8090"):
        self.router_url = router_url.rstrip('/')
        
    async def get_status(self):
        """Get and display router status"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.router_url}/status")
                if response.status_code == 200:
                    status = response.json()
                    print(f"Router Status: {status['router']}")
                    print(f"Total Sessions: {status.get('total_sessions', 0)}")
                    print("\nBackends:")
                    
                    if not status.get("backends"):
                        print("  No backends configured")
                        return
                        
                    for name, info in status["backends"].items():
                        status_emoji = "✓" if info["status"] == "healthy" else "✗"
                        print(f"  {status_emoji} {name}: {info['url']} ({info['status']})")
                        if info.get("consecutive_failures", 0) > 0:
                            print(f"    Failures: {info['consecutive_failures']}")
                else:
                    print(f"Error: HTTP {response.status_code}")
        except Exception as e:
            print(f"Error connecting to router: {e}")
            
    async def add_backend(self, name: str, url: str):
        """Add a new backend"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.router_url}/backends",
                    json={"name": name, "url": url}
                )
                if response.status_code == 200:
                    print(f"✓ Added backend '{name}' at {url}")
                else:
                    print(f"✗ Failed to add backend: HTTP {response.status_code}")
        except Exception as e:
            print(f"✗ Error adding backend: {e}")
            
    async def remove_backend(self, name: str):
        """Remove a backend"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.delete(
                    f"{self.router_url}/backends",
                    params={"name": name}
                )
                if response.status_code == 200:
                    print(f"✓ Removed backend '{name}'")
                else:
                    print(f"✗ Failed to remove backend: HTTP {response.status_code}")
        except Exception as e:
            print(f"✗ Error removing backend: {e}")
            
    async def list_backends(self):
        """List all backends in JSON format"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.router_url}/backends")
                if response.status_code == 200:
                    backends = response.json()
                    print(json.dumps(backends, indent=2))
                else:
                    print(f"Error: HTTP {response.status_code}")
        except Exception as e:
            print(f"Error: {e}")


@click.group()
@click.option("--router-url", default="http://localhost:8090", help="Router URL")
@click.pass_context
def cli(ctx, router_url: str):
    """MCP Router CLI - Manage router backends from command line"""
    ctx.ensure_object(dict)
    ctx.obj['cli'] = RouterCLI(router_url)


@cli.command()
@click.pass_context
def status(ctx):
    """Show router and backend status"""
    asyncio.run(ctx.obj['cli'].get_status())


@cli.command()
@click.argument('name')
@click.argument('url')
@click.pass_context
def add(ctx, name: str, url: str):
    """Add a new backend"""
    if not url.startswith(('http://', 'https://')):
        url = f"http://{url}"
    asyncio.run(ctx.obj['cli'].add_backend(name, url))


@cli.command()
@click.argument('name')
@click.pass_context
def remove(ctx, name: str):
    """Remove a backend"""
    asyncio.run(ctx.obj['cli'].remove_backend(name))


@cli.command()
@click.pass_context
def list(ctx):
    """List backends in JSON format"""
    asyncio.run(ctx.obj['cli'].list_backends())


@cli.command()
@click.pass_context
def tui(ctx):
    """Launch interactive TUI"""
    from router_manager import RouterManager, TUI
    manager = RouterManager(ctx.obj['cli'].router_url)
    tui_instance = TUI(manager)
    asyncio.run(tui_instance.run())


if __name__ == "__main__":
    cli()