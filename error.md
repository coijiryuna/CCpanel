sudo is already the newest version (1.9.16p2-3+deb13u2).
Summary:
  Upgrading: 0, Installing: 0, Removing: 0, Not Upgrading: 0
==> Systemd service + env
● ccpanel.service - CCPanel
     Loaded: loaded (/etc/systemd/system/ccpanel.service; enabled; preset: enabled)
     Active: activating (auto-restart) (Result: exit-code) since Sat 2026-08-15 15:58:27 WIB; 1s ago
 Invocation: c8ef1b13250f4e7db3b11b8186bf4702
    Process: 16523 ExecStart=/opt/ccpanel/.venv/bin/uvicorn server:app --host 0.0.0.0 --port 8888 (code=exited, status=1/FAILURE)
   Main PID: 16523 (code=exited, status=1/FAILURE)
   Mem peak: 18.5M
        CPU: 274ms

Aug 15 15:58:27 debian systemd[1]: ccpanel.service: Main process exited, co…LURE
Aug 15 15:58:27 debian systemd[1]: ccpanel.service: Failed with result 'exi…de'.
Hint: Some lines were ellipsized, use -l to show in full.
root@debian:~/CCpanel# journalctl -u ccpanel.service
Aug 15 11:29:55 debian systemd[1]: Started ccpanel.service - CCPanel.
Aug 15 11:29:57 debian uvicorn[10794]: /opt/ccpanel/core/hotlink.py:4: SyntaxWarning: invalid escape sequence '\.'
Aug 15 11:29:57 debian uvicorn[10794]:   `location ~* \.(gif|jpg|...)$ { valid_referers ...; if ($invalid_referer) { return 403; } }`
Aug 15 11:29:57 debian systemd[1]: Stopping ccpanel.service - CCPanel...
Aug 15 11:29:57 debian systemd[1]: ccpanel.service: Deactivated successfully.
Aug 15 11:29:57 debian systemd[1]: Stopped ccpanel.service - CCPanel.
Aug 15 11:29:57 debian systemd[1]: ccpanel.service: Consumed 1.980s CPU time, 48.2M memory peak.
-- Boot 0415c2b952564a4fa96fdfdbac378a0c --
Aug 15 13:30:41 debian systemd[1]: Started ccpanel.service - CCPanel.
Aug 15 13:30:42 debian uvicorn[15826]: Traceback (most recent call last):
Aug 15 13:30:42 debian uvicorn[15826]:   File "/opt/ccpanel/.venv/bin/uvicorn", line 8, in <module>
Aug 15 13:30:42 debian uvicorn[15826]:     sys.exit(main())
Aug 15 13:30:42 debian uvicorn[15826]:              ~~~~^^
Aug 15 13:30:42 debian uvicorn[15826]:   File "/opt/ccpanel/.venv/lib/python3.13/site-packages/click/core.py", line 1569, in __call__
Aug 15 13:30:42 debian uvicorn[15826]:     return self.main(*args, **kwargs)
Aug 15 13:30:42 debian uvicorn[15826]:            ~~~~~~~~~^^^^^^^^^^^^^^^^^
Aug 15 13:30:42 debian uvicorn[15826]:   File "/opt/ccpanel/.venv/lib/python3.13/site-packages/click/core.py", line 1490, in main
Aug 15 13:30:42 debian uvicorn[15826]:     rv = self.invoke(ctx)
Aug 15 13:30:42 debian uvicorn[15826]:   File "/opt/ccpanel/.venv/lib/python3.13/site-packages/click/core.py", line 1353, in invoke
Aug 15 13:30:42 debian uvicorn[15826]:     return ctx.invoke(self.callback, **ctx.params)
Aug 15 13:30:42 debian uvicorn[15826]:            ~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Aug 15 13:30:42 debian uvicorn[15826]:   File "/opt/ccpanel/.venv/lib/python3.13/site-packages/click/core.py", line 907, in invoke
Aug 15 13:30:42 debian uvicorn[15826]:     return callback(*args, **kwargs)
Aug 15 13:30:42 debian uvicorn[15826]:   File "/opt/ccpanel/.venv/lib/python3.13/site-packages/uvicorn/main.py", line 440, in main
Aug 15 13:30:42 debian uvicorn[15826]:     run(
Aug 15 13:30:42 debian uvicorn[15826]:     ~~~^
Aug 15 13:30:42 debian uvicorn[15826]:         app,
Aug 15 13:30:42 debian uvicorn[15826]:         ^^^^
Aug 15 13:30:42 debian uvicorn[15826]:     ...<48 lines>...
Aug 15 13:30:42 debian uvicorn[15826]:         reset_contextvars=reset_contextvars,
lines 8-30
-- Boot 0415c2b952564a4fa96fdfdbac378a0c --
Aug 15 13:30:41 debian systemd[1]: Started ccpanel.service - CCPanel.
Aug 15 13:30:42 debian uvicorn[15826]: Traceback (most recent call last):
Aug 15 13:30:42 debian uvicorn[15826]:   File "/opt/ccpanel/.venv/bin/uvicorn", line 8, in <module>
Aug 15 13:30:42 debian uvicorn[15826]:     sys.exit(main())
Aug 15 13:30:42 debian uvicorn[15826]:              ~~~~^^
Aug 15 13:30:42 debian uvicorn[15826]:   File "/opt/ccpanel/.venv/lib/python3.13/site-packages/click/core.py", line 1569, in __call__
Aug 15 13:30:42 debian uvicorn[15826]:     return self.main(*args, **kwargs)
Aug 15 13:30:42 debian uvicorn[15826]:            ~~~~~~~~~^^^^^^^^^^^^^^^^^
Aug 15 13:30:42 debian uvicorn[15826]:   File "/opt/ccpanel/.venv/lib/python3.13/site-packages/click/core.py", line 1490, in main
Aug 15 13:30:42 debian uvicorn[15826]:     rv = self.invoke(ctx)
Aug 15 13:30:42 debian uvicorn[15826]:   File "/opt/ccpanel/.venv/lib/python3.13/site-packages/click/core.py", line 1353, in invoke
Aug 15 13:30:42 debian uvicorn[15826]:     return ctx.invoke(self.callback, **ctx.params)
Aug 15 13:30:42 debian uvicorn[15826]:            ~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Aug 15 13:30:42 debian uvicorn[15826]:   File "/opt/ccpanel/.venv/lib/python3.13/site-packages/click/core.py", line 907, in invoke
Aug 15 13:30:42 debian uvicorn[15826]:     return callback(*args, **kwargs)
Aug 15 13:30:42 debian uvicorn[15826]:   File "/opt/ccpanel/.venv/lib/python3.13/site-packages/uvicorn/main.py", line 440, in main
Aug 15 13:30:42 debian uvicorn[15826]:     run(
Aug 15 13:30:42 debian uvicorn[15826]:     ~~~^
Aug 15 13:30:42 debian uvicorn[15826]:         app,
Aug 15 13:30:42 debian uvicorn[15826]:         ^^^^
Aug 15 13:30:42 debian uvicorn[15826]:     ...<48 lines>...
Aug 15 13:30:42 debian uvicorn[15826]:         reset_contextvars=reset_contextvars,
Aug 15 13:30:42 debian uvicorn[15826]:         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Aug 15 13:30:42 debian uvicorn[15826]:     )
Aug 15 13:30:42 debian uvicorn[15826]:     ^
Aug 15 13:30:42 debian uvicorn[15826]:   File "/opt/ccpanel/.venv/lib/python3.13/site-packages/uvicorn/main.py", line 609, in run
Aug 15 13:30:42 debian uvicorn[15826]:     config.load_app()
Aug 15 13:30:42 debian uvicorn[15826]:     ~~~~~~~~~~~~~~~^^
Aug 15 13:30:42 debian uvicorn[15826]:   File "/opt/ccpanel/.venv/lib/python3.13/site-packages/uvicorn/config.py", line 428, in load_app
Aug 15 13:30:42 debian uvicorn[15826]:     return import_from_string(self.app)
Aug 15 13:30:42 debian uvicorn[15826]:   File "/opt/ccpanel/.venv/lib/python3.13/site-packages/uvicorn/importer.py", line 19, in import_from_string
Aug 15 13:30:42 debian uvicorn[15826]:     module = importlib.import_module(module_str)
Aug 15 13:30:42 debian uvicorn[15826]:   File "/usr/lib/python3.13/importlib/__init__.py", line 88, in import_module
Aug 15 13:30:42 debian uvicorn[15826]:     return _bootstrap._gcd_import(name[level:], package, level)
Aug 15 13:30:42 debian uvicorn[15826]:            ~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Aug 15 13:30:42 debian uvicorn[15826]:   File "<frozen importlib._bootstrap>", line 1387, in _gcd_import
Aug 15 13:30:42 debian uvicorn[15826]:   File "<frozen importlib._bootstrap>", line 1360, in _find_and_load
Aug 15 13:30:42 debian uvicorn[15826]:   File "<frozen importlib._bootstrap>", line 1331, in _find_and_load_unlocked
Aug 15 13:30:42 debian uvicorn[15826]:   File "<frozen importlib._bootstrap>", line 935, in _load_unlocked
Aug 15 13:30:42 debian uvicorn[15826]:   File "<frozen importlib._bootstrap_external>", line 1026, in exec_module
Aug 15 13:30:42 debian uvicorn[15826]:   File "<frozen importlib._bootstrap>", line 488, in _call_with_frames_removed
Aug 15 13:30:42 debian uvicorn[15826]:   File "/opt/ccpanel/server.py", line 16, in <module>
Aug 15 13:30:42 debian uvicorn[15826]:     from fastapi import Request, HTTPException
Aug 15 13:30:42 debian uvicorn[15826]: ImportError: cannot import name 'Request' from 'fastapi' (/opt/ccpanel/.venv/lib/python3.13/site-packages/fastapi/__init__.py)
Aug 15 13:30:42 debian systemd[1]: ccpanel.service: Main process exited, code=exited, status=1/FAILURE
Aug 15 13:30:42 debian systemd[1]: ccpanel.service: Failed with result 'exit-code'.
