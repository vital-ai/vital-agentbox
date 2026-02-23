"""
Test FastAPI endpoints end-to-end using httpx TestClient.
"""

import asyncio
import httpx
from asgi_lifespan import LifespanManager


async def main():
    passed = 0
    failed = 0

    def check(name, condition, detail=""):
        nonlocal passed, failed
        if condition:
            passed += 1
            print(f"  ✓ {name}")
        else:
            failed += 1
            print(f"  ✗ {name}")
            if detail:
                print(f"      {detail}")

    print("=" * 60)
    print("TEST: FastAPI Endpoints")
    print("=" * 60)

    from agentbox.api.app import app

    async with LifespanManager(app) as manager:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=manager.app),
            base_url="http://test",
        ) as client:

            # --- Health ---
            print("\n--- health ---")
            r = await client.get("/health")
            check("GET /health status", r.status_code == 200)
            body = r.json()
            check("health status ok", body["status"] == "ok")
            check("health total 0", body["total"] == 0)

            # --- Create sandbox ---
            print("\n--- create sandbox ---")
            r = await client.post("/sandboxes", json={"sandbox_id": "s1"})
            check("POST /sandboxes 201", r.status_code == 201)
            body = r.json()
            check("sandbox_id matches", body["sandbox_id"] == "s1")
            check("state ready", body["state"] == "ready")

            # --- Duplicate ---
            r = await client.post("/sandboxes", json={"sandbox_id": "s1"})
            check("duplicate returns 409", r.status_code == 409)

            # --- List ---
            print("\n--- list sandboxes ---")
            r = await client.get("/sandboxes")
            check("GET /sandboxes 200", r.status_code == 200)
            check("list has 1", len(r.json()) == 1)

            # --- Get ---
            r = await client.get("/sandboxes/s1")
            check("GET /sandboxes/s1 200", r.status_code == 200)

            r = await client.get("/sandboxes/nope")
            check("GET missing 404", r.status_code == 404)

            # --- Execute shell ---
            print("\n--- execute shell ---")
            r = await client.post("/sandboxes/s1/execute", json={
                "code": "echo hello world",
                "language": "shell",
            })
            check("POST execute 200", r.status_code == 200)
            body = r.json()
            check("shell stdout", body["stdout"] == "hello world\n")
            check("shell exit_code", body["exit_code"] == 0)

            # --- Execute python ---
            print("\n--- execute python ---")
            r = await client.post("/sandboxes/s1/execute", json={
                "code": "print(2 + 3)",
                "language": "python",
            })
            body = r.json()
            check("python stdout", body["stdout"] == "5\n")
            check("python exit_code", body["exit_code"] == 0)

            # --- Execute error ---
            r = await client.post("/sandboxes/s1/execute", json={
                "code": "1/0",
                "language": "python",
            })
            body = r.json()
            check("error exit_code 1", body["exit_code"] == 1)
            check("error stderr", "ZeroDivisionError" in body["stderr"])

            # --- Execute on missing sandbox ---
            r = await client.post("/sandboxes/nope/execute", json={
                "code": "echo hi",
                "language": "shell",
            })
            check("execute missing 404", r.status_code == 404)

            # --- Files: write ---
            print("\n--- file operations ---")
            r = await client.post("/sandboxes/s1/files/write", json={
                "path": "/api_test.txt",
                "content": "api content\n",
            })
            check("POST write 201", r.status_code == 201)

            # --- Files: read ---
            r = await client.get("/sandboxes/s1/files/read", params={"path": "/api_test.txt"})
            check("GET read 200", r.status_code == 200)
            body = r.json()
            check("read content", body["content"] == "api content\n")
            check("read exists", body["exists"] is True)

            # --- Files: read missing ---
            r = await client.get("/sandboxes/s1/files/read", params={"path": "/nope.txt"})
            body = r.json()
            check("read missing exists=false", body["exists"] is False)

            # --- Files: mkdir ---
            r = await client.post("/sandboxes/s1/files/mkdir", json={"path": "/api_dir/nested"})
            check("POST mkdir 201", r.status_code == 201)

            # --- Files: list ---
            r = await client.get("/sandboxes/s1/files", params={"path": "/"})
            check("GET list 200", r.status_code == 200)
            entries = r.json()["entries"]
            check("list has entries", len(entries) > 0)

            # --- Files: copy ---
            r = await client.post("/sandboxes/s1/files/copy", json={
                "src": "/api_test.txt",
                "dst": "/api_dir/copied.txt",
            })
            check("POST copy 200", r.status_code == 200)

            # --- Files: delete ---
            r = await client.delete("/sandboxes/s1/files", params={"path": "/api_dir/copied.txt"})
            check("DELETE file 200", r.status_code == 200)

            # --- Cross-boundary: shell writes, python reads via API ---
            print("\n--- cross-boundary via API ---")
            await client.post("/sandboxes/s1/execute", json={
                "code": 'echo "from api shell" > /cross_api.txt',
                "language": "shell",
            })
            r = await client.post("/sandboxes/s1/execute", json={
                "code": "print(open('/cross_api.txt').read().strip())",
                "language": "python",
            })
            body = r.json()
            check("cross-boundary shell→python", body["stdout"] == "from api shell\n")

            # --- Metrics ---
            print("\n--- metrics ---")
            r = await client.get("/metrics")
            check("GET /metrics 200", r.status_code == 200)
            m = r.json()
            check("metrics total 1", m["total"] == 1)

            # --- Destroy ---
            print("\n--- destroy ---")
            r = await client.delete("/sandboxes/s1")
            check("DELETE /sandboxes/s1 204", r.status_code == 204)

            r = await client.delete("/sandboxes/s1")
            check("DELETE missing 404", r.status_code == 404)

            r = await client.get("/sandboxes")
            check("list empty after destroy", len(r.json()) == 0)

    # --- Summary ---
    print(f"\n{'=' * 60}")
    total = passed + failed
    print(f"RESULTS: {passed}/{total} passed, {failed} failed")
    print(f"{'=' * 60}")

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
