"""The gateway client against a real local HTTP server (no cluster needed)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from app.gateway import GatewayClient, GatewayError


def serve(status, body):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def log_message(self, *_):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, GatewayClient(f"http://127.0.0.1:{server.server_port}", timeout=5)


def test_ok_reply_is_passed_through():
    server, client = serve(200, {"verdict": "likely_meets", "reason": "fine", "counts": {}})
    assert client.assess("note", "criterion") == {"verdict": "likely_meets", "reason": "fine"}
    server.shutdown()


def test_safety_refusal_is_recorded_not_raised():
    server, client = serve(422, {"detail": "masking incomplete"})
    assert client.assess("note", "criterion")["verdict"] == "refused"
    server.shutdown()


def test_server_errors_raise_so_the_job_retries():
    server, client = serve(502, {"detail": "model unavailable"})
    try:
        client.assess("note", "criterion")
    except GatewayError:
        server.shutdown()
        return
    raise AssertionError("expected GatewayError")
