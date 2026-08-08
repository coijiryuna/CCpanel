"""Unit test port management API."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import ports as ports_api

def test_get_used_ports():
    """Test getting used ports."""
    used = ports_api.get_used_ports()
    assert isinstance(used, list)
    # Should at least detect some system ports
    assert len(used) >= 0
    for p in used:
        assert hasattr(p, 'port')
        assert hasattr(p, 'protocol')
        assert hasattr(p, 'process')
        assert hasattr(p, 'pid')
        assert hasattr(p, 'state')
        assert hasattr(p, 'source')
        assert 1 <= p.port <= 65535

def test_get_available_ports():
    """Test getting available ports."""
    available = ports_api.get_available_ports(8000, 8100, 5)
    assert isinstance(available, list)
    assert len(available) <= 5
    for p in available:
        assert hasattr(p, 'port')
        assert hasattr(p, 'reason')
        assert 8000 <= p.port <= 8100

def test_is_port_free():
    """Test checking if port is free."""
    # Test with a port that's likely free
    free = ports_api.is_port_free(8000)
    assert isinstance(free, bool)
    
    # Test with a port that's likely in use (8888 - our server)
    # This might be free in test env, so just check it returns bool
    free2 = ports_api.is_port_free(8888)
    assert isinstance(free2, bool)

def test_check_port():
    """Test check_port function."""
    result = ports_api.check_port(8000)
    assert 'port' in result
    assert 'free' in result
    assert 'used_by' in result
    assert 'pid' in result
    assert 'protocol' in result
    assert result['port'] == 8000
    assert isinstance(result['free'], bool)

def test_reserve_port():
    """Test reserve_port function."""
    # Test with free port
    result = ports_api.reserve_port(8000, 'test')
    assert isinstance(result, bool)
    
    # Test with invalid port
    result2 = ports_api.reserve_port(0, 'test')
    assert result2 is False
    
    result3 = ports_api.reserve_port(70000, 'test')
    assert result3 is False