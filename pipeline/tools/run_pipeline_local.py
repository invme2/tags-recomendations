"""run_pipeline_local.py — local Windows/Linux runner for Shopify_Pipeline.ipynb.

The notebook is Colab-targeted (uses google.colab.drive / files / userdata,
hardcoded `/content/...` paths). This runner adapts it to local execution
WITHOUT modifying the committed notebook on disk:

  1. Reads the notebook with nbformat.
  2. Patches in-memory Cell 1 (`PROJECT_DIR` / `DB_LOCAL`) to read env vars.
  3. Prepends a setup cell that mocks `google.colab.{drive,userdata,files}`
     so the original imports work as no-ops.
  4. Pre-populates a local pipeline.db with products parsed from a CSV
     (so Cell 1's resume-path triggers — no Excel upload needed).
  5. Executes via nbclient, streaming per-cell outputs to stdout.
  6. Saves the executed notebook and prints a status summary from the DB.

USAGE:
    python pipeline/tools/run_pipeline_local.py --csv "C:/path/to/products.csv"
    python pipeline/tools/run_pipeline_local.py --csv "..." --name beauty-essentials --limit 2

The CSV is expected to have one product per line, separator `;` or `,`
between name and URL (extra columns ignored). EPROLO URLs only.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

# Force UTF-8 stdout/stderr — notebook cells print box-drawing chars and
# emojis which cp1251 (default Windows console encoding) can't represent.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import nbformat
from dotenv import load_dotenv
from nbclient import NotebookClient

REPO_ROOT = Path(__file__).resolve().parents[2]
NOTEBOOK = REPO_ROOT / "pipeline" / "Shopify_Pipeline.ipynb"
ENV_FILE = REPO_ROOT / ".env"
RUNS_DIR = REPO_ROOT / "runs"


SETUP_CELL_HEADER = r"""# === Local runner setup (auto-injected by run_pipeline_local.py) ===
import os, sys, types

# Mock google.colab modules — notebook designed for Colab.
_colab = types.ModuleType('google.colab')
_drive = types.ModuleType('google.colab.drive')
_drive.mount = lambda *a, **k: print(f'  [mock] drive.mount({a}) - skipped (local run)')
_userdata = types.ModuleType('google.colab.userdata')
_userdata.get = lambda key: os.environ.get(key, '')
_files = types.ModuleType('google.colab.files')
def _smart_upload():
    # Mock for colab_files.upload() that scans cwd for .xlsx and returns
    # them as if just uploaded. Lets Cell 9 (Collections to Shopify) read
    # the SEO Excel that Cell 7 just saved, instead of demanding manual upload.
    import glob
    found = sorted(glob.glob('*.xlsx'))
    if not found:
        print('  [mock] files.upload() - no local .xlsx in cwd')
        return {}
    result = {}
    for f in found:
        with open(f, 'rb') as fp:
            result[f] = fp.read()
    print(f'  [mock] files.upload() - returning {len(result)} local xlsx: {found}')
    return result
_files.upload = _smart_upload
_files.download = lambda *a, **k: print(f'  [mock] files.download({a}) - skipped')
_colab.drive = _drive
_colab.userdata = _userdata
_colab.files = _files
_google = sys.modules.get('google')
if _google is None:
    _google = types.ModuleType('google')
    sys.modules['google'] = _google
_google.colab = _colab
sys.modules['google.colab'] = _colab
sys.modules['google.colab.drive'] = _drive
sys.modules['google.colab.userdata'] = _userdata
sys.modules['google.colab.files'] = _files

print('Local runner: google.colab mocked')

# Force Anthropic SDK to use 30-minute read timeout — default 10 min was
# tripping on Designer calls that legitimately take 8-10 min to generate
# the full 35-section JSON. Without this fix every Designer call hits
# timeout, retries 4 times, ~40 min wasted per product.
try:
    import anthropic
    _orig_anthropic_init = anthropic.Anthropic.__init__
    def _patched_anthropic_init(self, *a, **kw):
        kw.setdefault('timeout', 1800.0)  # 30 min
        _orig_anthropic_init(self, *a, **kw)
    anthropic.Anthropic.__init__ = _patched_anthropic_init
    if hasattr(anthropic, 'AsyncAnthropic'):
        _orig_async_init = anthropic.AsyncAnthropic.__init__
        def _patched_async_init(self, *a, **kw):
            kw.setdefault('timeout', 1800.0)
            _orig_async_init(self, *a, **kw)
        anthropic.AsyncAnthropic.__init__ = _patched_async_init
    print('  anthropic SDK: timeout patched to 1800s (was 600s default)')
except ImportError:
    print('  anthropic SDK not yet imported — timeout patch will be retried later')
"""


def build_setup_cell(env_vars: dict) -> str:
    """Compose the setup cell: mock google.colab + force-inject env vars
    from the runner's process (bypass nbclient env-inheritance issues on
    Windows where existing empty ANTHROPIC_API_KEY in user env would
    win over .env). Values are literal-escaped — no f-string injection."""
    lines = [SETUP_CELL_HEADER, "# === Forced env injection ==="]
    for key, val in env_vars.items():
        # repr() handles all quoting/escaping safely
        lines.append(f"os.environ[{key!r}] = {val!r}")
    lines.append("")
    lines.append("for k in sorted(['ANTHROPIC_API_KEY','SHOPIFY_STORE',"
                 "'SHOPIFY_CLIENT_ID','SHOPIFY_CLIENT_SECRET',"
                 "'DATAFORSEO_LOGIN','DATAFORSEO_PASSWORD','OPENAI_API_KEY',"
                 "'EPROLO_STATE_FILE','PIPELINE_PROJECT_DIR','PIPELINE_DB_LOCAL']):")
    lines.append("    v = os.environ.get(k, '')")
    lines.append("    if v:")
    lines.append("        masked = v[:6] + '...' + v[-4:] if len(v) > 14 else 'SET'")
    lines.append("        print(f'  {k}: {masked}')")
    lines.append("    else:")
    lines.append("        print(f'  {k}: MISSING')")
    return "\n".join(lines)


def parse_csv(path: Path) -> List[Tuple[str, str]]:
    """Read (name, url) pairs. Supports `name;url` or `name,url` per line.
    Trailing commas tolerated. Lines without a recognizable URL are skipped."""
    pairs: List[Tuple[str, str]] = []
    with path.open(encoding="utf-8") as f:
        for raw in f:
            line = raw.strip().lstrip("﻿")  # strip BOM if present
            if not line:
                continue
            for sep in (";", ","):
                if sep in line:
                    parts = [p.strip() for p in line.split(sep)]
                    # Find the part that looks like a URL
                    url_idx = next((i for i, p in enumerate(parts)
                                    if p.startswith("http")), None)
                    if url_idx is not None and url_idx > 0:
                        name = parts[url_idx - 1] or parts[0]
                        url = parts[url_idx].rstrip(",").rstrip(";")
                        pairs.append((name, url))
                        break
    return pairs


def populate_db(db_path: Path, products: List[Tuple[str, str]]) -> None:
    """Create pipeline.db with the products table populated.
    Schema matches what Cell 1 of the notebook creates."""
    db = sqlite3.connect(str(db_path))
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, eprolo_url TEXT NOT NULL,
            status TEXT DEFAULT 'pending', error_msg TEXT,
            scrape_json TEXT, image_urls_json TEXT,
            stage1_json TEXT, stage2_json TEXT, final_html TEXT,
            seo_title TEXT, seo_description TEXT, url_handle TEXT,
            shopify_product_id TEXT, product_tags TEXT,
            variants_json TEXT, cost_usd REAL DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS collections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_name TEXT, seo_title TEXT NOT NULL,
            seo_handle TEXT, full_url TEXT,
            meta_title TEXT, meta_description TEXT,
            shopify_collection_id TEXT
        );
        CREATE TABLE IF NOT EXISTS product_collections (
            product_id INTEGER, collection_id INTEGER, UNIQUE(product_id, collection_id)
        );
        CREATE TABLE IF NOT EXISTS seo_state (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS seo_keywords (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword TEXT NOT NULL,
            collection_name TEXT,
            volume INTEGER DEFAULT 0,
            kd INTEGER DEFAULT 0,
            cpc REAL DEFAULT 0,
            competition TEXT,
            UNIQUE(keyword, collection_name)
        );
    """)
    for col in ("shopify_product_id seo_title seo_description url_handle product_tags "
                "variants_json seo_keywords primary_collection extra_css strategy_json "
                "assets_json").split():
        try:
            db.execute(f"ALTER TABLE products ADD COLUMN {col} TEXT")
        except sqlite3.OperationalError:
            pass
    for col in ("shopify_collection_id",):
        try:
            db.execute(f"ALTER TABLE collections ADD COLUMN {col} TEXT")
        except sqlite3.OperationalError:
            pass
    try:
        db.execute("ALTER TABLE collections ADD COLUMN total_volume INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        db.execute('ALTER TABLE collections ADD COLUMN top_keywords TEXT DEFAULT ""')
    except sqlite3.OperationalError:
        pass
    # Idempotency: re-calling populate_db on an existing DB with a new (or
    # overlapping) CSV must NOT duplicate rows. UNIQUE index + INSERT OR IGNORE
    # below = drip-feed batches without RESET_DB.
    try:
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_products_eprolo_url "
                   "ON products(eprolo_url) WHERE eprolo_url != ''")
    except sqlite3.OperationalError:
        pass

    inserted = 0
    skipped = 0
    for name, url in products:
        cur = db.execute(
            "INSERT OR IGNORE INTO products (name, eprolo_url, status) VALUES (?, ?, 'pending')",
            (name, url),
        )
        if cur.rowcount > 0:
            inserted += 1
        else:
            skipped += 1
    db.commit()
    db.close()
    if skipped:
        print(f"  populate_db: inserted {inserted} new, skipped {skipped} dupes "
              "(eprolo_url UNIQUE)")
    else:
        print(f"  populate_db: inserted {inserted} rows")


def transform_config_cell(source: str) -> str:
    """Make `/content/...` paths overridable via env vars."""
    source = source.replace(
        "PROJECT_DIR = '/content/drive/MyDrive/shopify_pipeline'",
        "PROJECT_DIR = os.environ.get('PIPELINE_PROJECT_DIR', "
        "'/content/drive/MyDrive/shopify_pipeline')",
    )
    source = source.replace(
        "DB_LOCAL = '/content/pipeline.db'",
        "DB_LOCAL = os.environ.get('PIPELINE_DB_LOCAL', '/content/pipeline.db')",
    )
    # Strip Unix-only `2>/dev/null` shell redirection from pip/playwright lines
    source = source.replace("2>/dev/null", "")
    return source


class StreamingClient(NotebookClient):
    """NotebookClient that prints each cell's stdout/stderr/errors as it
    finishes, so a long-running notebook isn't a black box."""

    async def async_execute_cell(self, cell, cell_index, execution_count=None,
                                 store_history=True):
        ts = time.strftime("%H:%M:%S")
        marker = f"\n[{ts}] === cell #{cell_index} ({cell.cell_type}) ==="
        if cell.cell_type == "code":
            first_line = (cell.source.split("\n", 1)[0] or "").strip()
            # Strip non-printable / box-drawing so marker never raises on cp1251.
            safe = first_line.encode("ascii", errors="replace").decode("ascii")
            marker += f"  // {safe[:100]}"
        try:
            print(marker, flush=True)
        except UnicodeEncodeError:
            print(marker.encode("ascii", errors="replace").decode("ascii"), flush=True)
        try:
            result = await super().async_execute_cell(
                cell, cell_index, execution_count, store_history
            )
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] cell #{cell_index} RAISED: {type(e).__name__}: {e}", flush=True)
            raise
        for out in (getattr(cell, "outputs", None) or []):
            ot = getattr(out, "output_type", "")
            if ot == "stream":
                print(f"  {getattr(out, 'text', '')}".rstrip(), flush=True)
            elif ot == "error":
                print(f"  ERROR: {out.ename}: {out.evalue}", flush=True)
                for line in (getattr(out, "traceback", []) or [])[:10]:
                    print(f"    {line}", flush=True)
            elif ot in ("execute_result", "display_data"):
                data = getattr(out, "data", {}) or {}
                txt = data.get("text/plain", "")
                if txt:
                    print(f"  => {txt[:500]}", flush=True)
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--name", default=None,
                        help="run-dir name under runs/ (default: timestamp)")
    parser.add_argument("--limit", type=int, default=None,
                        help="only first N products from CSV")
    parser.add_argument("--reset-db", action="store_true",
                        help="wipe pipeline.db if it exists in the run dir")
    parser.add_argument("--skip-prescrape", action="store_true",
                        help="don't auto-run prescrape_eprolo.py before executing notebook")
    parser.add_argument("--no-execute", action="store_true",
                        help="setup DB + (optionally) prescrape, but don't execute notebook")
    args = parser.parse_args()

    if not ENV_FILE.exists():
        sys.exit(f".env not found at {ENV_FILE} — create it first")
    load_dotenv(ENV_FILE, override=True)
    print(f"loaded .env from {ENV_FILE} (override=True)")

    if not NOTEBOOK.exists():
        sys.exit(f"notebook not found: {NOTEBOOK}")

    products = parse_csv(args.csv)
    if not products:
        sys.exit(f"no products parsed from {args.csv}")
    if args.limit:
        products = products[: args.limit]
    print(f"parsed {len(products)} products from {args.csv}")
    for i, (n, u) in enumerate(products, 1):
        print(f"  [{i:2d}] {n[:70]}")
        print(f"       {u}")

    run_name = args.name or datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = RUNS_DIR / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "output").mkdir(exist_ok=True)
    # DB_LOCAL must be a DIFFERENT file from DB_PATH = PROJECT_DIR/pipeline.db,
    # else Cell 1's `shutil.copy(DB_LOCAL, DB_PATH)` backup raises SameFileError.
    db_dir = run_dir / ".db"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / "pipeline.db"  # working DB (DB_LOCAL)
    if args.reset_db and db_path.exists():
        db_path.unlink()
        print(f"reset-db: removed {db_path}")
    if db_path.exists():
        existing = sqlite3.connect(str(db_path))
        n_before = existing.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        n_done   = existing.execute("SELECT COUNT(*) FROM products WHERE status='done'").fetchone()[0]
        n_error  = existing.execute("SELECT COUNT(*) FROM products WHERE status='error'").fetchone()[0]
        existing.close()
        print(f"DB exists: {db_path} ({n_before} products, {n_done} done, {n_error} error — resume mode)")
        # Always merge new CSV — populate_db uses INSERT OR IGNORE so duplicate
        # eprolo_url rows from the CSV are silently dropped. New URLs queue up
        # as 'pending'. Existing products in any stage are NOT touched.
        populate_db(db_path, products)
        new_db = sqlite3.connect(str(db_path))
        n_after = new_db.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        new_db.close()
        added = n_after - n_before
        if added:
            print(f"  merged {added} new products from CSV (total now {n_after})")
    else:
        populate_db(db_path, products)
        print(f"created {db_path} with {len(products)} products")

    os.environ["PIPELINE_PROJECT_DIR"] = str(run_dir).replace("\\", "/")
    os.environ["PIPELINE_DB_LOCAL"] = str(db_path).replace("\\", "/")
    # Force RESET_DB=False — never wipe the pre-populated DB
    os.environ.setdefault("RESET_DB", "False")
    # Parallelize per-product loop (notebook default = 1, serial).
    # 3 is a safe ceiling under Anthropic + Shopify rate limits.
    os.environ.setdefault("BATCH_CONCURRENCY", "3")

    if not args.skip_prescrape:
        state_file = os.environ.get("EPROLO_STATE_FILE", "")
        if state_file and Path(state_file).exists():
            print()
            print(f"=== prescrape phase (sync_playwright, bypasses Windows asyncio bug) ===")
            cmd = [sys.executable,
                   str(REPO_ROOT / "pipeline" / "tools" / "prescrape_eprolo.py"),
                   "--db", str(db_path),
                   "--state", state_file]
            print(f"  $ {' '.join(cmd)}")
            r = subprocess.run(cmd, env=os.environ.copy())
            if r.returncode != 0:
                print(f"  prescrape exited {r.returncode} — continuing anyway")
        else:
            print(f"=== prescrape skipped (no EPROLO_STATE_FILE) — Bug A will trigger ===")

    if args.no_execute:
        print()
        print("=== --no-execute: stopping after setup/prescrape ===")
        # Show DB state and exit
        db = sqlite3.connect(str(db_path))
        for s in ("done", "scraped", "pending", "error"):
            n = db.execute("SELECT COUNT(*) FROM products WHERE status=?", (s,)).fetchone()[0]
            if n:
                print(f"  products/{s:8s} {n}")
        db.close()
        return 0

    nb = nbformat.read(NOTEBOOK, as_version=4)
    print(f"notebook loaded: {len(nb.cells)} cells")

    patched_config = False
    for i, c in enumerate(nb.cells):
        if (c.cell_type == "code"
                and "PROJECT_DIR = '/content/drive/MyDrive" in c.source):
            c.source = transform_config_cell(c.source)
            patched_config = True
            print(f"  patched config cell #{i}")
            break
    if not patched_config:
        sys.exit("could not find config cell to patch (expected line with PROJECT_DIR)")

    env_for_injection = {}
    for key in ("ANTHROPIC_API_KEY", "SHOPIFY_STORE", "SHOPIFY_CLIENT_ID",
                "SHOPIFY_CLIENT_SECRET", "DATAFORSEO_LOGIN", "DATAFORSEO_PASSWORD",
                "OPENAI_API_KEY", "EPROLO_STATE_FILE", "PIPELINE_PROJECT_DIR",
                "PIPELINE_DB_LOCAL", "RESET_DB", "BATCH_CONCURRENCY",
                "DESIGNER_PROVIDER", "DEEPSEEK_API_KEY", "DEEPSEEK_MODEL"):
        val = os.environ.get(key, "")
        if val:
            env_for_injection[key] = val
    print(f"  injecting {len(env_for_injection)} env vars into setup cell")
    setup_source = build_setup_cell(env_for_injection)
    setup_cell = nbformat.v4.new_code_cell(source=setup_source)
    nb.cells.insert(0, setup_cell)
    print("  injected setup cell at index 0")

    exec_nb_path = run_dir / "_executable.ipynb"
    nbformat.write(nb, exec_nb_path)
    print(f"wrote {exec_nb_path}")

    print()
    print(f"=== Executing notebook IN-PROCESS via IPython.InteractiveShell ===")
    print(f"(live stdout streaming, like Colab; no kernel subprocess)")
    print(f"working dir: {run_dir}")
    print()

    # Set ProactorEventLoopPolicy so async_playwright can spawn subprocess on
    # Windows (ipykernel forces SelectorEventLoop which breaks subprocess).
    # In-process IPython doesn't have that constraint — we choose the policy.
    if sys.platform == "win32":
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            print("  asyncio policy: WindowsProactorEventLoopPolicy")
        except Exception as e:
            print(f"  could not set Proactor policy: {e}")

    orig_cwd = os.getcwd()
    os.chdir(str(run_dir))
    n_errored = 0
    try:
        from IPython.core.interactiveshell import InteractiveShell
        shell = InteractiveShell.instance()
        try:
            shell.colors = "NoColor"
        except Exception:
            pass

        total = len(nb.cells)
        for idx, cell in enumerate(nb.cells):
            if cell.cell_type != "code":
                continue
            ts = time.strftime("%H:%M:%S")
            first = (cell.source.split("\n", 1)[0] or "").strip()
            preview = first.encode("ascii", errors="replace").decode("ascii")[:100]
            print(f"\n[{ts}] === cell #{idx}/{total - 1} ===  // {preview}", flush=True)
            try:
                result = shell.run_cell(cell.source, store_history=True)
            except KeyboardInterrupt:
                print("\n*** Interrupted by user", flush=True)
                break
            except Exception as e:
                print(f"  [SHELL EXCEPTION] {type(e).__name__}: {e}", flush=True)
                n_errored += 1
                continue
            if getattr(result, "error_before_exec", None):
                print(f"  [COMPILE ERROR] {result.error_before_exec}", flush=True)
                n_errored += 1
            if getattr(result, "error_in_exec", None):
                err = result.error_in_exec
                print(f"  [RUNTIME ERROR] {type(err).__name__}: {err}", flush=True)
                n_errored += 1
    finally:
        os.chdir(orig_cwd)
        print(f"\n=== executed: {n_errored} cell errors ===")

    print()
    print("=== Final DB state ===")
    db = sqlite3.connect(str(db_path))
    db.row_factory = sqlite3.Row
    for s in ("done", "html_ready", "content_ready", "vision_done",
              "images_uploaded", "scraped", "pending", "error"):
        n = db.execute("SELECT COUNT(*) FROM products WHERE status=?", (s,)).fetchone()[0]
        if n:
            print(f"  products/{s:18s} {n}")
    n_coll = db.execute("SELECT COUNT(*) FROM collections").fetchone()[0]
    n_pc = db.execute("SELECT COUNT(*) FROM product_collections").fetchone()[0]
    print(f"  collections        {n_coll}")
    print(f"  product_collections {n_pc}")
    errored = db.execute(
        "SELECT name, error_msg FROM products WHERE status='error' LIMIT 5"
    ).fetchall()
    if errored:
        print()
        print("=== Errored products (first 5) ===")
        for r in errored:
            print(f"  {r['name'][:60]}")
            print(f"    {(r['error_msg'] or '')[:200]}")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
