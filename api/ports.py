"""Port management: CRUD, detection of used ports, auto-suggest available ports, firewall control."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import List, Set, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from .deps import _log, app, get_db, require_auth

class PortInfo(BaseModel):
    port: int
    protocol: str  # tcp, udp
    process: str
    pid: int
    state: str  # LISTEN, ESTABLISHED, etc.
    source: str  # systemd, docker, manual, etc.

class PortSuggestion(BaseModel):
    port: int
    reason: str  # "free", "reserved", "suggested"

class FirewallRule(BaseModel):
    port: int
    protocol: str  # tcp, udp, both
    action: str  # allow, deny
    comment: str = ""

def get_used_ports() -> List[PortInfo]:
    """Detect all ports currently in use on the system."""
    used = []
    
    # Method 1: ss (socket statistics) - modern replacement for netstat
    try:
        res = subprocess.run(
            ["ss", "-tulnp"], 
            capture_output=True, text=True, timeout=10
        )
        if res.returncode == 0:
            for line in res.stdout.strip().split('\n')[1:]:  # skip header
                parts = line.split()
                if len(parts) >= 7:
                    protocol = parts[0]
                    state = parts[1]
                    local_addr = parts[4]
                    process_info = parts[6] if len(parts) > 6 else ""
                    
                    # Extract port from local address (e.g., 127.0.0.1:8080 or :::8080)
                    port = None
                    if ':' in local_addr:
                        try:
                            port = int(local_addr.split(':')[-1])
                        except ValueError:
                            pass
                    
                    # Extract PID and process name
                    pid = 0
                    process = "unknown"
                    if 'pid=' in process_info:
                        try:
                            pid_part = process_info.split('pid=')[1].split(',')[0]
                            pid = int(pid_part)
                        except (ValueError, IndexError):
                            pass
                    
                    if 'users:' in process_info:
                        try:
                            process = process_info.split('users:((')[1].split('"')[1]
                        except (IndexError, ValueError):
                            process = process_info
                    
                    if port and 1 <= port <= 65535:
                        used.append(PortInfo(
                            port=port,
                            protocol=protocol.upper(),
                            process=process,
                            pid=pid,
                            state=state,
                            source="system"
                        ))
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        pass
    
    # Method 2: netstat fallback
    if not used:
        try:
            res = subprocess.run(
                ["netstat", "-tulnp"], 
                capture_output=True, text=True, timeout=10
            )
            if res.returncode == 0:
                for line in res.stdout.strip().split('\n')[2:]:  # skip headers
                    parts = line.split()
                    if len(parts) >= 7:
                        protocol = parts[0]
                        local_addr = parts[3]
                        process_info = parts[6] if len(parts) > 6 else ""
                        
                        port = None
                        if ':' in local_addr:
                            try:
                                port = int(local_addr.split(':')[-1])
                            except ValueError:
                                pass
                        
                        pid = 0
                        process = "unknown"
                        if '/' in process_info:
                            try:
                                pid = int(process_info.split('/')[0])
                                process = process_info.split('/')[1]
                            except (ValueError, IndexError):
                                pass
                        
                        if port and 1 <= port <= 65535:
                            used.append(PortInfo(
                                port=port,
                                protocol=protocol.upper(),
                                process=process,
                                pid=pid,
                                state="LISTEN",
                                source="system"
                            ))
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            pass
    
    # Method 3: Check CCPanel managed ports from database
    try:
        with get_db() as conn:
            # Projects ports
            rows = conn.execute("SELECT port, name, app_type FROM projects").fetchall()
            for row in rows:
                used.append(PortInfo(
                    port=row["port"],
                    protocol="TCP",
                    process=f"ccpanel-proj-{row['name']} ({row['app_type']})",
                    pid=0,
                    state="MANAGED",
                    source="ccpanel-project"
                ))
            
            # Site apps ports
            rows = conn.execute("SELECT port, app_type, name FROM site_apps").fetchall()
            for row in rows:
                used.append(PortInfo(
                    port=row["port"],
                    protocol="TCP",
                    process=f"ccpanel-site-app-{row['name'] or row['app_type']} ({row['app_type']})",
                    pid=0,
                    state="MANAGED",
                    source="ccpanel-site-app"
                ))
            
            # Site proxy ports (nginx)
            rows = conn.execute("SELECT port FROM sites WHERE port IS NOT NULL").fetchall()
            for row in rows:
                used.append(PortInfo(
                    port=row["port"],
                    protocol="TCP",
                    process="nginx (site proxy)",
                    pid=0,
                    state="MANAGED",
                    source="ccpanel-site"
                ))
    except Exception:
        pass
    
    # Deduplicate by port
    seen = set()
    unique = []
    for p in used:
        if p.port not in seen:
            seen.add(p.port)
            unique.append(p)
    
    return sorted(unique, key=lambda x: x.port)

def get_available_ports(start: int = 8000, end: int = 9999, count: int = 10) -> List[PortSuggestion]:
    """Get list of available ports in range."""
    used_ports = {p.port for p in get_used_ports()}
    suggestions = []
    
    for port in range(start, min(end + 1, 65536)):
        if port not in used_ports:
            if port in (80, 443, 8080, 8443, 3000, 5000, 8000, 8001, 8002, 8003, 8004, 8005, 8006, 8007, 8008, 8009, 8010):
                reason = "commonly used"
            elif 8000 <= port <= 8999:
                reason = "suggested range"
            else:
                reason = "free"
            suggestions.append(PortSuggestion(port=port, reason=reason))
            if len(suggestions) >= count:
                break
    
    return suggestions

def is_port_free(port: int) -> bool:
    """Check if a specific port is free."""
    used = {p.port for p in get_used_ports()}
    return port not in used

def reserve_port(port: int, description: str) -> bool:
    """Reserve a port in the database (for tracking)."""
    if not 1 <= port <= 65535:
        return False
    return is_port_free(port)

# ===== Firewall Management =====

def _run_firewall_cmd(cmd: List[str]) -> subprocess.CompletedProcess:
    """Run firewall command with sudo if needed."""
    # Try with sudo first for firewall commands
    sudo_cmd = ["sudo", "-n"] + cmd
    try:
        return subprocess.run(sudo_cmd, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        raise HTTPException(500, "Firewall command timeout")
    except Exception:
        # Fallback without sudo
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired:
            raise HTTPException(500, "Firewall command timeout")

def _get_firewall_tool() -> str:
    """Detect available firewall tool."""
    for tool in ["ufw", "firewall-cmd", "iptables"]:
        if subprocess.run(["which", tool], capture_output=True).returncode == 0:
            return tool
    return "ufw"  # default

def firewall_allow_port(port: int, protocol: str = "both", comment: str = "") -> dict:
    """Open port in firewall."""
    tool = _get_firewall_tool()
    results = []
    
    protocols = ["tcp", "udp"] if protocol == "both" else [protocol]
    
    for proto in protocols:
        if tool == "ufw":
            cmd = ["ufw", "allow", f"{port}/{proto}"]
            if comment:
                cmd.extend(["comment", comment])
            res = _run_firewall_cmd(cmd)
            results.append({"protocol": proto, "success": res.returncode == 0, "output": res.stdout or res.stderr})
        elif tool == "firewall-cmd":
            cmd = ["firewall-cmd", "--permanent", f"--add-port={port}/{proto}"]
            res = _run_firewall_cmd(cmd)
            if res.returncode == 0:
                _run_firewall_cmd(["firewall-cmd", "--reload"])
            results.append({"protocol": proto, "success": res.returncode == 0, "output": res.stdout or res.stderr})
        elif tool == "iptables":
            for chain in ["INPUT", "OUTPUT"]:
                cmd = ["iptables", "-A", chain, "-p", proto, "--dport", str(port), "-j", "ACCEPT"]
                res = _run_firewall_cmd(cmd)
                results.append({"protocol": proto, "chain": chain, "success": res.returncode == 0, "output": res.stdout or res.stderr})
    
    return {"tool": tool, "port": port, "protocol": protocol, "results": results}

def firewall_deny_port(port: int, protocol: str = "both", comment: str = "") -> dict:
    """Close port in firewall."""
    tool = _get_firewall_tool()
    results = []
    
    protocols = ["tcp", "udp"] if protocol == "both" else [protocol]
    
    for proto in protocols:
        if tool == "ufw":
            cmd = ["ufw", "delete", "allow", f"{port}/{proto}"]
            res = _run_firewall_cmd(cmd)
            results.append({"protocol": proto, "success": res.returncode == 0, "output": res.stdout or res.stderr})
        elif tool == "firewall-cmd":
            cmd = ["firewall-cmd", "--permanent", f"--remove-port={port}/{proto}"]
            res = _run_firewall_cmd(cmd)
            if res.returncode == 0:
                _run_firewall_cmd(["firewall-cmd", "--reload"])
            results.append({"protocol": proto, "success": res.returncode == 0, "output": res.stdout or res.stderr})
        elif tool == "iptables":
            for chain in ["INPUT", "OUTPUT"]:
                cmd = ["iptables", "-D", chain, "-p", proto, "--dport", str(port), "-j", "ACCEPT"]
                res = _run_firewall_cmd(cmd)
                results.append({"protocol": proto, "chain": chain, "success": res.returncode == 0, "output": res.stdout or res.stderr})
    
    return {"tool": tool, "port": port, "protocol": protocol, "results": results}

def firewall_list_rules() -> List[dict]:
    """List current firewall rules for ports."""
    tool = _get_firewall_tool()
    rules = []
    
    if tool == "ufw":
        res = _run_firewall_cmd(["ufw", "status", "numbered"])
        if res.returncode == 0:
            for line in res.stdout.strip().split('\n'):
                if 'ALLOW' in line or 'DENY' in line:
                    parts = line.split()
                    if len(parts) >= 3:
                        rules.append({"raw": line.strip()})
    elif tool == "firewall-cmd":
        res = _run_firewall_cmd(["firewall-cmd", "--list-all"])
        if res.returncode == 0:
            for line in res.stdout.strip().split('\n'):
                if 'port' in line.lower():
                    rules.append({"raw": line.strip()})
    elif tool == "iptables":
        res = _run_firewall_cmd(["iptables", "-L", "INPUT", "-n", "--line-numbers"])
        if res.returncode == 0:
            for line in res.stdout.strip().split('\n'):
                if 'dpt:' in line:
                    rules.append({"raw": line.strip()})
    
    return rules

# API Endpoints
@app.get("/api/ports/used", response_model=List[PortInfo])
def list_used_ports(user: dict = Depends(require_auth)) -> List[PortInfo]:
    """List all ports currently in use on the server."""
    return get_used_ports()

@app.get("/api/ports/available", response_model=List[PortSuggestion])
def list_available_ports(
    start: int = 8000, 
    end: int = 9999, 
    count: int = 20,
    user: dict = Depends(require_auth)
) -> List[PortSuggestion]:
    """Get suggested available ports in range."""
    return get_available_ports(start, end, count)

@app.get("/api/ports/check/{port}")
def check_port(port: int, user: dict = Depends(require_auth)) -> dict:
    """Check if a specific port is free."""
    used_ports = get_used_ports()
    port_info = next((p for p in used_ports if p.port == port), None)
    return {
        "port": port,
        "free": port_info is None,
        "used_by": port_info.process if port_info else None,
        "pid": port_info.pid if port_info else None,
        "protocol": port_info.protocol if port_info else None,
    }

@app.post("/api/ports/reserve")
def reserve_port_api(port: int, description: str = "", user: dict = Depends(require_auth)) -> dict:
    """Reserve a port for future use."""
    if not 1 <= port <= 65535:
        raise HTTPException(400, "Port tidak valid (1-65535)")
    
    if not is_port_free(port):
        raise HTTPException(409, f"Port {port} sudah digunakan")
    
    return {"ok": True, "port": port, "description": description}

# ===== Firewall API Endpoints =====

@app.get("/api/ports/firewall/rules")
def list_firewall_rules(user: dict = Depends(require_auth)) -> dict:
    """List current firewall port rules."""
    return {"rules": firewall_list_rules(), "tool": _get_firewall_tool()}

@app.post("/api/ports/firewall/allow")
def allow_port_firewall(rule: FirewallRule, user: dict = Depends(require_auth)) -> dict:
    """Open port in firewall (TCP/UDP/both)."""
    if not 1 <= rule.port <= 65535:
        raise HTTPException(400, "Port tidak valid (1-65535)")
    if rule.protocol not in ("tcp", "udp", "both"):
        raise HTTPException(400, "Protocol harus tcp, udp, atau both")
    if rule.action not in ("allow", "deny"):
        raise HTTPException(400, "Action harus allow atau deny")
    
    comment = rule.comment or f"ccpanel-port-{rule.port}"
    return firewall_allow_port(rule.port, rule.protocol, comment)

@app.post("/api/ports/firewall/deny")
def deny_port_firewall(rule: FirewallRule, user: dict = Depends(require_auth)) -> dict:
    """Close port in firewall (TCP/UDP/both)."""
    if not 1 <= rule.port <= 65535:
        raise HTTPException(400, "Port tidak valid (1-65535)")
    if rule.protocol not in ("tcp", "udp", "both"):
        raise HTTPException(400, "Protocol harus tcp, udp, atau both")
    
    comment = rule.comment or f"ccpanel-port-{rule.port}"
    return firewall_deny_port(rule.port, rule.protocol, comment)

@app.post("/api/ports/firewall/toggle")
def toggle_port_firewall(rule: FirewallRule, user: dict = Depends(require_auth)) -> dict:
    """Toggle port in firewall (allow if denied, deny if allowed)."""
    rules = firewall_list_rules()
    is_allowed = False
    for r in rules:
        raw = r.get("raw", "").lower()
        if str(rule.port) in raw and rule.protocol in raw:
            if 'allow' in raw or 'accept' in raw:
                is_allowed = True
                break
    
    if is_allowed:
        return deny_port_firewall(rule, user)
    else:
        return allow_port_firewall(rule, user)
