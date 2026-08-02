// CCPanel CLI — kelola panel dari terminal. Stdlib only.
//
// Config: env CCPANEL_API (default http://127.0.0.1:8888) + token via login.
// Token disimpan di ~/.ccpanel.json (0600).
package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"
)

const configPath = ".ccpanel.json"

type config struct {
	API   string `json:"api"`
	Token string `json:"token"`
}

func apiBase() string {
	if v := os.Getenv("CCPANEL_API"); v != "" {
		return strings.TrimRight(v, "/")
	}
	return "http://127.0.0.1:8888"
}

func cfgFile() string {
	if v := os.Getenv("CCPANEL_CONFIG"); v != "" {
		return v
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return configPath
	}
	return filepath.Join(home, configPath)
}

func loadCfg() config {
	b, err := os.ReadFile(cfgFile())
	if err != nil {
		return config{API: apiBase()}
	}
	var c config
	json.Unmarshal(b, &c)
	if c.API == "" {
		c.API = apiBase()
	}
	return c
}

func saveCfg(c config) error {
	b, _ := json.MarshalIndent(c, "", "  ")
	return os.WriteFile(cfgFile(), b, 0o600)
}

func doReq(method, path, token string, body any, out any) error {
	var rdr io.Reader
	if body != nil {
		b, _ := json.Marshal(body)
		rdr = bytes.NewReader(b)
	}
	req, err := http.NewRequest(method, apiBase()+path, rdr)
	if err != nil {
		return err
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	client := &http.Client{Timeout: 30 * time.Second}
	res, err := client.Do(req)
	if err != nil {
		return err
	}
	defer res.Body.Close()
	data, _ := io.ReadAll(res.Body)
	if res.StatusCode >= 400 {
		var e struct{ Detail string }
		json.Unmarshal(data, &e)
		if e.Detail != "" {
			return errors.New(e.Detail)
		}
		return fmt.Errorf("HTTP %d: %s", res.StatusCode, strings.TrimSpace(string(data)))
	}
	if out != nil && len(data) > 0 {
		return json.Unmarshal(data, out)
	}
	return nil
}

func main() {
	if len(os.Args) < 2 {
		usage()
		os.Exit(1)
	}
	cmd, args := os.Args[1], os.Args[2:]
	var err error
	switch cmd {
	case "login":
		err = cmdLogin(args)
	case "sites":
		err = cmdSites(args)
	case "dbs":
		err = cmdDbs(args)
	case "backups":
		err = cmdBackups(args)
	case "dashboard":
		err = cmdDashboard()
	case "logs":
		err = cmdLogs(args)
	case "help", "-h", "--help":
		usage()
	default:
		err = fmt.Errorf("perintah tidak dikenal: %s", cmd)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "Error:", err)
		os.Exit(1)
	}
}

func usage() {
	fmt.Print(`CCPanel CLI

Pemakaian:
  ccpanel login <username> <password>     simpan token
  ccpanel sites                           daftar site
  ccpanel sites create <domain>           buat site
  ccpanel sites delete <id>               hapus site (pindah trash)
  ccpanel sites enable|disable <id>       aktif/nonaktif site
  ccpanel sites php <id> <versi>          ganti PHP (static|php8.1|php8.2|php8.3)
  ccpanel dbs                             daftar database
  ccpanel dbs create <nama> [user] [pass] buat database (host localhost)
  ccpanel dbs delete <id>                 hapus database
  ccpanel backups                         daftar backup
  ccpanel backups site <id>               backup site
  ccpanel backups db <id>                 backup database
  ccpanel dashboard                       statistik panel
  ccpanel logs [limit]                    log audit (default 20)

Env: CCPANEL_API (default http://127.0.0.1:8888), CCPANEL_CONFIG (default ~/.ccpanel.json)
`)
}

// --------------------------------------------------------------- commands

func cmdLogin(args []string) error {
	if len(args) < 2 {
		return errors.New("pemakaian: ccpanel login <username> <password>")
	}
	var out struct {
		Token string `json:"token"`
	}
	if err := doReq("POST", "/api/login", "", map[string]string{
		"username": args[0], "password": args[1],
	}, &out); err != nil {
		return err
	}
	c := config{API: apiBase(), Token: out.Token}
	if err := saveCfg(c); err != nil {
		return err
	}
	fmt.Println("Login OK. Token disimpan di", cfgFile())
	return nil
}

func token() (string, error) {
	t := os.Getenv("CCPANEL_TOKEN")
	if t != "" {
		return t, nil
	}
	c := loadCfg()
	if c.Token == "" {
		return "", errors.New("belum login — jalankan: ccpanel login <username> <password>")
	}
	return c.Token, nil
}

type site struct {
	ID          int    `json:"id"`
	Domain      string `json:"domain"`
	Enabled     bool   `json:"enabled"`
	WafEnabled  bool   `json:"waf_enabled"`
	Webserver   string `json:"webserver"`
	PhpVersion  string `json:"php_version"`
	CreatedAt   string `json:"created_at"`
}

func cmdSites(args []string) error {
	tok, err := token()
	if err != nil {
		return err
	}
	if len(args) == 0 {
		var sites []site
		if err := doReq("GET", "/api/sites", tok, nil, &sites); err != nil {
			return err
		}
		fmt.Printf("%-4s %-32s %-8s %-8s %s\n", "ID", "DOMAIN", "STATUS", "WEBSERVER", "PHP")
		for _, s := range sites {
			st := "nonaktif"
			if s.Enabled {
				st = "aktif"
			}
			fmt.Printf("%-4d %-32s %-8s %-8s %s\n", s.ID, s.Domain, st, s.Webserver, s.PhpVersion)
		}
		return nil
	}
	sub, rest := args[0], args[1:]
	switch sub {
	case "create":
		if len(rest) < 1 {
			return errors.New("pemakaian: ccpanel sites create <domain>")
		}
		var s site
		if err := doReq("POST", "/api/sites", tok, map[string]string{"domain": rest[0]}, &s); err != nil {
			return err
		}
		fmt.Printf("Site dibuat: %s (id %d)\n", s.Domain, s.ID)
		return nil
	case "delete":
		if len(rest) < 1 {
			return errors.New("pemakaian: ccpanel sites delete <id>")
		}
		return doReq("DELETE", "/api/sites/"+rest[0], tok, nil, nil)
	case "enable", "disable":
		if len(rest) < 1 {
			return fmt.Errorf("pemakaian: ccpanel sites %s <id>", sub)
		}
		return doReq("POST", "/api/sites/"+rest[0]+"/"+sub, tok, nil, nil)
	case "php":
		if len(rest) < 2 {
			return errors.New("pemakaian: ccpanel sites php <id> <versi>")
		}
		return doReq("PUT", "/api/sites/"+rest[0]+"/php", tok,
			map[string]string{"php_version": rest[1]}, nil)
	default:
		return fmt.Errorf("sub-perintah tidak dikenal: %s", sub)
	}
}

type dbRow struct {
	ID     int    `json:"id"`
	DbName string `json:"db_name"`
	DbUser string `json:"db_user"`
	DbHost string `json:"db_host"`
	DbType string `json:"db_type"`
}

func cmdDbs(args []string) error {
	tok, err := token()
	if err != nil {
		return err
	}
	if len(args) == 0 {
		var dbs []dbRow
		if err := doReq("GET", "/api/dbs", tok, nil, &dbs); err != nil {
			return err
		}
		fmt.Printf("%-4s %-28s %-28s %-10s %s\n", "ID", "NAMA", "USER", "HOST", "TIPE")
		for _, d := range dbs {
			fmt.Printf("%-4d %-28s %-28s %-10s %s\n", d.ID, d.DbName, d.DbUser, d.DbHost, d.DbType)
		}
		return nil
	}
	sub, rest := args[0], args[1:]
	switch sub {
	case "create":
		if len(rest) < 1 {
			return errors.New("pemakaian: ccpanel dbs create <nama> [user] [pass]")
		}
		body := map[string]string{"db_name": rest[0]}
		if len(rest) > 1 {
			body["db_user"] = rest[1]
		}
		if len(rest) > 2 {
			body["password"] = rest[2]
		}
		var d dbRow
		if err := doReq("POST", "/api/dbs", tok, body, &d); err != nil {
			return err
		}
		fmt.Printf("DB dibuat: %s (user %s@%s)\n", d.DbName, d.DbUser, d.DbHost)
		return nil
	case "delete":
		if len(rest) < 1 {
			return errors.New("pemakaian: ccpanel dbs delete <id>")
		}
		return doReq("DELETE", "/api/dbs/"+rest[0], tok, nil, nil)
	default:
		return fmt.Errorf("sub-perintah tidak dikenal: %s", sub)
	}
}

type backupItem struct {
	Name string `json:"name"`
	Size int64  `json:"size"`
}

func cmdBackups(args []string) error {
	tok, err := token()
	if err != nil {
		return err
	}
	if len(args) == 0 {
		var backups []backupItem
		if err := doReq("GET", "/api/backups", tok, nil, &backups); err != nil {
			return err
		}
		for _, b := range backups {
			fmt.Printf("%-50s %d B\n", b.Name, b.Size)
		}
		return nil
	}
	sub, rest := args[0], args[1:]
	if len(rest) < 1 {
		return fmt.Errorf("pemakaian: ccpanel backups %s <id>", sub)
	}
	return doReq("POST", "/api/backups/"+sub+"/"+rest[0], tok, nil, nil)
}

func cmdDashboard() error {
	tok, err := token()
	if err != nil {
		return err
	}
	var d struct {
		Counts struct {
			Sites int `json:"sites"`
			Dbs   int `json:"dbs"`
			Ftp   int `json:"ftp"`
			Users int `json:"users"`
		} `json:"counts"`
		TotalSize int64 `json:"total_size"`
	}
	if err := doReq("GET", "/api/dashboard", tok, nil, &d); err != nil {
		return err
	}
	fmt.Printf("Sites: %d   DB: %d   FTP: %d   Users: %d   Total: %d B\n",
		d.Counts.Sites, d.Counts.Dbs, d.Counts.Ftp, d.Counts.Users, d.TotalSize)
	return nil
}

type logEntry struct {
	Ts     string `json:"ts"`
	User   string `json:"user"`
	Action string `json:"action"`
	Detail string `json:"detail"`
}

func cmdLogs(args []string) error {
	tok, err := token()
	if err != nil {
		return err
	}
	limit := "20"
	if len(args) > 0 {
		limit = args[0]
	}
	var logs []logEntry
	if err := doReq("GET", "/api/logs?limit="+limit, tok, nil, &logs); err != nil {
		return err
	}
	for _, l := range logs {
		fmt.Printf("%s  %-12s  %-20s  %s\n", l.Ts[:19], l.User, l.Action, l.Detail)
	}
	return nil
}
