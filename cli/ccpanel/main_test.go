package main

import (
	"os"
	"path/filepath"
	"testing"
)

// TestConfigRoundtrip: config JSON round-trip dengan permission 0600.
func TestConfigRoundtrip(t *testing.T) {
	dir := t.TempDir()
	cfg := filepath.Join(dir, "cfg.json")
	os.Setenv("CCPANEL_CONFIG", cfg)
	defer os.Unsetenv("CCPANEL_CONFIG")

	if err := saveCfg(config{API: "http://x:1", Token: "abc"}); err != nil {
		t.Fatal(err)
	}
	info, err := os.Stat(cfg)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Fatalf("permission = %o, ingin 600", info.Mode().Perm())
	}
	c := loadCfg()
	if c.API != "http://x:1" || c.Token != "abc" {
		t.Fatalf("roundtrip gagal: %+v", c)
	}
}

// TestApiBaseDefault: tanpa env, default localhost:8888.
func TestApiBaseDefault(t *testing.T) {
	os.Unsetenv("CCPANEL_API")
	if got := apiBase(); got != "http://127.0.0.1:8888" {
		t.Fatalf("apiBase = %s", got)
	}
	os.Setenv("CCPANEL_API", "http://example.com:9999/")
	defer os.Unsetenv("CCPANEL_API")
	if got := apiBase(); got != "http://example.com:9999" {
		t.Fatalf("apiBase env = %s", got)
	}
}

// TestTokenFromEnv: CCPANEL_TOKEN menang tanpa file config.
func TestTokenFromEnv(t *testing.T) {
	os.Setenv("CCPANEL_TOKEN", "env-token")
	defer os.Unsetenv("CCPANEL_TOKEN")
	os.Setenv("CCPANEL_CONFIG", filepath.Join(t.TempDir(), "none.json"))
	defer os.Unsetenv("CCPANEL_CONFIG")

	tok, err := token()
	if err != nil {
		t.Fatal(err)
	}
	if tok != "env-token" {
		t.Fatalf("token = %s", tok)
	}
}
