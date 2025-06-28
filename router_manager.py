#!/usr/bin/env python3
"""
MCP Router Manager - CLI TUI for managing router backends
"""

import asyncio
import json
import sys
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

import httpx
import click


@dataclass
class Backend:
    """Represents a backend server"""
    name: str
    url: str
    status: str
    last_healthy: Optional[str] = None
    consecutive_failures: int = 0


class RouterManager:
    """Manager for MCP Router backends"""
    
    def __init__(self, router_url: str = "http://localhost:8090"):
        self.router_url = router_url.rstrip('/')
        
    async def get_status(self) -> Dict[str, Any]:
        """Get router status"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.router_url}/status")
                if response.status_code == 200:
                    return response.json()
                else:
                    raise Exception(f"HTTP {response.status_code}")
        except Exception as e:
            raise Exception(f"Failed to connect to router: {e}")
            
    async def list_backends(self) -> List[Backend]:
        """List all backends"""
        status = await self.get_status()
        backends = []
        for name, info in status.get("backends", {}).items():
            backends.append(Backend(
                name=name,
                url=info["url"],
                status=info["status"],
                last_healthy=info.get("last_healthy"),
                consecutive_failures=info.get("consecutive_failures", 0)
            ))
        return backends
        
    async def add_backend(self, name: str, url: str) -> bool:
        """Add a new backend"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.router_url}/backends",
                    json={"name": name, "url": url}
                )
                return response.status_code == 200
        except Exception:
            return False
            
    async def remove_backend(self, name: str) -> bool:
        """Remove a backend"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.delete(
                    f"{self.router_url}/backends",
                    params={"name": name}
                )
                return response.status_code == 200
        except Exception:
            return False


class TUI:
    """Simple text-based user interface"""
    
    def __init__(self, manager: RouterManager):
        self.manager = manager
        
    def clear_screen(self):
        """Clear the screen"""
        print("\033[2J\033[H", end="")
        
    def print_header(self):
        """Print header"""
        print("=" * 80)
        print(" " * 25 + "MCP Dev Router Manager")
        print("=" * 80)
        print()
        
    def print_backends(self, backends: List[Backend]):
        """Print backends table"""
        if not backends:
            print("No backends configured.")
            return
            
        # Calculate column widths
        name_width = max(len(b.name) for b in backends) + 2
        url_width = max(len(b.url) for b in backends) + 2
        status_width = 12
        
        # Print header
        print(f"{'Name':<{name_width}} {'URL':<{url_width}} {'Status':<{status_width}} {'Failures'}")
        print("-" * (name_width + url_width + status_width + 10))
        
        # Print backends
        for backend in backends:
            status_color = self.get_status_color(backend.status)
            status_display = f"{status_color}{backend.status}\033[0m"
            
            print(f"{backend.name:<{name_width}} {backend.url:<{url_width}} {status_display:<{status_width + 9}} {backend.consecutive_failures}")
            
    def get_status_color(self, status: str) -> str:
        """Get color code for status"""
        colors = {
            "healthy": "\033[92m",    # Green
            "unhealthy": "\033[91m",  # Red
            "checking": "\033[93m",   # Yellow
        }
        return colors.get(status, "")
        
    def print_menu(self):
        """Print main menu"""
        print()
        print("Options:")
        print("  [1] Refresh")
        print("  [2] Add Backend")
        print("  [3] Remove Backend")
        print("  [4] Edit Backend")
        print("  [q] Quit")
        print()
        
    def get_input(self, prompt: str) -> str:
        """Get user input"""
        return input(f"{prompt}: ").strip()
        
    async def add_backend_flow(self):
        """Add backend flow"""
        print("\n--- Add New Backend ---")
        name = self.get_input("Backend name")
        if not name:
            print("Name cannot be empty!")
            input("Press Enter to continue...")
            return
            
        url = self.get_input("Backend URL (e.g., http://localhost:8080)")
        if not url:
            print("URL cannot be empty!")
            input("Press Enter to continue...")
            return
            
        if not url.startswith(('http://', 'https://')):
            url = f"http://{url}"
            
        print(f"\nAdding backend '{name}' at '{url}'...")
        success = await self.manager.add_backend(name, url)
        
        if success:
            print("✓ Backend added successfully!")
        else:
            print("✗ Failed to add backend!")
            
        input("Press Enter to continue...")
        
    async def remove_backend_flow(self, backends: List[Backend]):
        """Remove backend flow"""
        if not backends:
            print("No backends to remove!")
            input("Press Enter to continue...")
            return
            
        print("\n--- Remove Backend ---")
        for i, backend in enumerate(backends, 1):
            print(f"  [{i}] {backend.name} ({backend.url})")
            
        choice = self.get_input("Select backend to remove (number)")
        
        try:
            index = int(choice) - 1
            if 0 <= index < len(backends):
                backend = backends[index]
                confirm = self.get_input(f"Remove '{backend.name}'? (y/N)")
                
                if confirm.lower() == 'y':
                    print(f"Removing backend '{backend.name}'...")
                    success = await self.manager.remove_backend(backend.name)
                    
                    if success:
                        print("✓ Backend removed successfully!")
                    else:
                        print("✗ Failed to remove backend!")
                else:
                    print("Cancelled.")
            else:
                print("Invalid selection!")
        except ValueError:
            print("Invalid input!")
            
        input("Press Enter to continue...")
        
    async def edit_backend_flow(self, backends: List[Backend]):
        """Edit backend flow"""
        if not backends:
            print("No backends to edit!")
            input("Press Enter to continue...")
            return
            
        print("\n--- Edit Backend ---")
        for i, backend in enumerate(backends, 1):
            print(f"  [{i}] {backend.name} ({backend.url})")
            
        choice = self.get_input("Select backend to edit (number)")
        
        try:
            index = int(choice) - 1
            if 0 <= index < len(backends):
                backend = backends[index]
                
                print(f"\nEditing '{backend.name}':")
                print(f"Current URL: {backend.url}")
                
                new_name = self.get_input(f"New name (current: {backend.name})")
                new_url = self.get_input(f"New URL (current: {backend.url})")
                
                if not new_name:
                    new_name = backend.name
                if not new_url:
                    new_url = backend.url
                elif not new_url.startswith(('http://', 'https://')):
                    new_url = f"http://{new_url}"
                
                if new_name != backend.name or new_url != backend.url:
                    # Remove old backend and add new one
                    print(f"Updating backend...")
                    
                    remove_success = await self.manager.remove_backend(backend.name)
                    if remove_success:
                        add_success = await self.manager.add_backend(new_name, new_url)
                        if add_success:
                            print("✓ Backend updated successfully!")
                        else:
                            print("✗ Failed to add updated backend!")
                            # Try to restore original
                            await self.manager.add_backend(backend.name, backend.url)
                    else:
                        print("✗ Failed to remove old backend!")
                else:
                    print("No changes made.")
            else:
                print("Invalid selection!")
        except ValueError:
            print("Invalid input!")
            
        input("Press Enter to continue...")
        
    async def run(self):
        """Run the TUI"""
        while True:
            try:
                self.clear_screen()
                self.print_header()
                
                # Get current status
                try:
                    status = await self.manager.get_status()
                    backends = await self.manager.list_backends()
                    
                    print(f"Router Status: \033[92m{status['router']}\033[0m")
                    print(f"Total Sessions: {status.get('total_sessions', 0)}")
                    print()
                    
                    self.print_backends(backends)
                    self.print_menu()
                    
                except Exception as e:
                    print(f"\033[91mError: {e}\033[0m")
                    print("\nMake sure the MCP router is running on the configured port.")
                    print()
                    print("Options:")
                    print("  [q] Quit")
                    print()
                    backends = []
                
                choice = self.get_input("Select option").lower()
                
                if choice == 'q':
                    break
                elif choice == '1':
                    continue  # Refresh (loop will reload)
                elif choice == '2':
                    await self.add_backend_flow()
                elif choice == '3':
                    await self.remove_backend_flow(backends)
                elif choice == '4':
                    await self.edit_backend_flow(backends)
                else:
                    print("Invalid option!")
                    input("Press Enter to continue...")
                    
            except KeyboardInterrupt:
                break
                
        print("\nGoodbye!")


@click.command()
@click.option("--router-url", default="http://localhost:8090", help="Router URL")
def main(router_url: str):
    """MCP Router Manager - Interactive CLI for managing router backends"""
    manager = RouterManager(router_url)
    tui = TUI(manager)
    
    try:
        asyncio.run(tui.run())
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)


if __name__ == "__main__":
    main()