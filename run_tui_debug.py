# -*- coding: utf-8 -*-
"""Runner debug: jalankan TUI dan tangkap semua error ke file log."""
import sys, traceback, io

LOG = r"C:\Users\NEXUSDEV\Desktop\auto claim\tui_dbg.txt"

class Tee:
    def __init__(self, *streams):
        self.streams = streams
    def write(self, s):
        for st in self.streams:
            try:
                st.write(s)
                st.flush()
            except Exception:
                pass
    def flush(self):
        for st in self.streams:
            try:
                st.flush()
            except Exception:
                pass

logf = open(LOG, "w", encoding="utf-8", buffering=1)
sys.stdout = Tee(sys.__stdout__, logf)
sys.stderr = Tee(sys.__stderr__, logf)

sys.argv = ["auto_claim_tui.py", "--test"]

print("=== TUI DEBUG RUN START ===", flush=True)
try:
    import runpy
    runpy.run_path(r"C:\Users\NEXUSDEV\Desktop\auto claim\auto_claim_tui.py",
                   run_name="__main__")
    print("=== TUI RUN SELESAI NORMAL ===", flush=True)
except SystemExit as e:
    print(f"=== SystemExit: {e} ===", flush=True)
except BaseException:
    print("=== EXCEPTION ===", flush=True)
    traceback.print_exc()
    print("=== END EXCEPTION ===", flush=True)
finally:
    logf.close()
