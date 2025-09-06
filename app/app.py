from flask import Flask, jsonify, request
from core.logging import JsonLogger
from core.metrics import Metrics
from core.redis_client import RedisClient
from core.db import DB
from core.health import HealthChecker
from services.checkoutService import CheckoutService

app = Flask(__name__)

# init infra
log = JsonLogger(service="api")
metrics = Metrics()
redis_client = RedisClient(logger=log, metrics=metrics)
db = DB(logger=log, metrics=metrics)
health = HealthChecker(logger=log, metrics=metrics, redis_client=redis_client, db=db)
checkout_service = CheckoutService(logger=log, metrics=metrics, redis_client=redis_client, db=db)

@app.get("/live")
def live():
    return jsonify(health.liveness())

@app.get("/health")
def healthRoute():
    body, code = health.readiness()
    return jsonify(body), code

@app.get("/metrics")
def prom():
    return metrics.expose()

@app.get("/enquire/<item_id>")
def enquire(item_id):
    body, code = checkout_service.enquire(item_id)
    return jsonify(body), code

# Support GET with ?qty= and POST; also support GET with /<qty> path
@app.route("/checkout/<item_id>", methods=["GET", "POST"])
@app.get("/checkout/<item_id>/<int:qty>")
def checkout(item_id, qty=None):
    user_id = request.args.get("user")
    if qty is None:
        try:
            qty = int(request.args.get("qty", "1"))
        except ValueError:
            qty = 1
    body, code = checkout_service.checkout(user_id=user_id, item_id=item_id, qty=qty)
    return jsonify(body), code

@app.get("/")
def home():
    return jsonify(
        message="AICS",
        try_enquire="/enquire/I001 or /enquire/1",
        try_checkout="/checkout/I001?qty=2&user=u1",
        health="/health", live="/live", metrics="/metrics"
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
