# Postgres DB adapter
import os, time, random
import psycopg
from psycopg.rows import dict_row

SCHEMA = """
CREATE TABLE IF NOT EXISTS inventory(
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT NOT NULL,
  price_cents INTEGER NOT NULL,
  qty INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS orders(
  id SERIAL PRIMARY KEY,
  item_id INTEGER NOT NULL REFERENCES inventory(id),
  qty INTEGER NOT NULL,
  unit_price_cents INTEGER NOT NULL,
  total_cents INTEGER NOT NULL,
  created_ts DOUBLE PRECISION NOT NULL
);
"""

def _env(name, default=None, alt=None):
    return os.getenv(name, os.getenv(alt, default) if alt else default)

class DB:
    def __init__(self, logger=None, metrics=None):
        self.log = logger
        self.metrics = metrics
        user = _env("DB_USER", default="app", alt="POSTGRES_USER")
        pwd  = _env("DB_PASS", default="app", alt="POSTGRES_PASSWORD")
        host = _env("DB_HOST", default="postgres")
        port = _env("DB_PORT", default="5432")
        name = _env("DB_NAME", default=_env("POSTGRES_DB", default="postgres"))
        self.dsn = _env("DB_DSN", f"postgresql://{user}:{pwd}@{host}:{port}/{name}")
        self._init()

    def _connect(self):
        return psycopg.connect(self.dsn, autocommit=False, row_factory=dict_row)

    def _init(self):
        with self._connect() as con:
            with con.cursor() as cur:
                cur.execute(SCHEMA)
                cur.execute("SELECT COUNT(*) AS n FROM inventory")
                n = cur.fetchone()["n"]
                if n == 0:
                    rows = []
                    for i in range(1, 101):
                        rows.append({
                            "id": i,
                            "name": f"Item-{i:03d}",
                            "description": f"Demo item {i} description",
                            "price_cents": random.choice([999,1299,1999,2999,4999,129900]),
                            "qty": random.randint(5,50),
                        })
                    cur.executemany(
                        "INSERT INTO inventory(id,name,description,price_cents,qty) "
                        "VALUES(%(id)s,%(name)s,%(description)s,%(price_cents)s,%(qty)s)", rows
                    )
            con.commit()
        if self.log: self.log.info(msg="postgres schema ready/seeded")

    # ---- health ----
    def health(self):
        t0 = time.time()
        try:
            with self._connect() as con:
                with con.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
            if self.metrics:
                self.metrics.DB_LAT.labels("health").observe(time.time()-t0)
                self.metrics.DB_OPS.labels("health","ok").inc()
            return True
        except Exception as e:
            if self.metrics: self.metrics.DB_OPS.labels("health","error").inc()
            if self.log: self.log.error(route="/health", msg="db error", err=str(e))
            return False

    # ---- item retrieval ----
    def get_item(self, item_id: int):
        t0 = time.time()
        try:
            with self._connect() as con:
                with con.cursor() as cur:
                    cur.execute(
                        "SELECT id, name, description, price_cents, qty FROM inventory WHERE id=%s",
                        (item_id,)
                    )
                    row = cur.fetchone()
            if self.metrics:
                self.metrics.DB_LAT.labels("get_item").observe(time.time()-t0)
                self.metrics.DB_OPS.labels("get_item","ok").inc()
            return row  # dict or None
        except Exception as e:
            if self.metrics: self.metrics.DB_OPS.labels("get_item","error").inc()
            if self.log: self.log.error(route="/enquire", msg="db get_item error", err=str(e))
            return None

    def get_stock_by_id(self, item_id: int):
        t0 = time.time()
        try:
            with self._connect() as con:
                with con.cursor() as cur:
                    cur.execute("SELECT qty FROM inventory WHERE id=%s", (item_id,))
                    row = cur.fetchone()
                    qty = row["qty"] if row else None
            if self.metrics:
                self.metrics.DB_LAT.labels("get_stock").observe(time.time()-t0)
                self.metrics.DB_OPS.labels("get_stock","ok").inc()
            return qty
        except Exception as e:
            if self.metrics: self.metrics.DB_OPS.labels("get_stock","error").inc()
            if self.log: self.log.error(route="/enquire", msg="db get_stock error", err=str(e))
            return None

    # ---- purchase (atomic) ----
    def purchase(self, item_id: int, qty: int):
        t0 = time.time()
        try:
            with self._connect() as con:
                with con.cursor() as cur:
                    cur.execute("""
                        UPDATE inventory
                           SET qty = qty - %s
                         WHERE id = %s AND qty >= %s
                     RETURNING price_cents, qty;
                    """, (qty, item_id, qty))
                    row = cur.fetchone()
                    if not row:
                        con.rollback()
                        if self.metrics:
                            self.metrics.DB_LAT.labels("purchase").observe(time.time()-t0)
                            self.metrics.DB_OPS.labels("purchase","ok").inc()
                        return None  # out of stock

                    price_cents, new_qty = int(row["price_cents"]), int(row["qty"])
                    total = price_cents * qty
                    cur.execute("""
                        INSERT INTO orders(item_id, qty, unit_price_cents, total_cents, created_ts)
                        VALUES (%s,%s,%s,%s,%s)
                    """, (item_id, qty, price_cents, total, time.time()))
                con.commit()

            if self.metrics:
                self.metrics.DB_LAT.labels("purchase").observe(time.time()-t0)
                self.metrics.DB_OPS.labels("purchase","ok").inc()
            return {
                "order": {
                    "item_id": item_id, "qty": qty,
                    "unit_price_cents": price_cents, "total_cents": total
                },
                "new_qty": new_qty
            }
        except Exception as e:
            if self.metrics: self.metrics.DB_OPS.labels("purchase","error").inc()
            if self.log: self.log.error(route="/checkout", msg="db purchase error", err=str(e))
            return None
